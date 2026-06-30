# ==========================================
# PROJECT: INVESTMENT DASHBOARD
# VERSION: v1.9.5 (Naver Real Estate Live Tracking Engine)
# DATE: 2026-06-29
# AUTHOR: CTO & 제대리 (Gemini)
# DESCRIPTION: 네이버 부동산 실매물 최저가 추적 알고리즘 탑재 및 관심 매물 알림 파이프라인 개통
# ==========================================
import os
import requests
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv

from backend.app.services.kr_stock import KrStockService
from backend.app.services.us_stock import UsStockService
from backend.app.services.exchange_rate import ExchangeRateService

load_dotenv()

api_blueprint = Blueprint("api", __name__)

def get_supabase():
    from supabase import create_client, Client
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        return create_client(url.rstrip('/'), key)
    except Exception:
        return None

# 네이버 실매물 가격 트래킹 내부 헬퍼 함수
def get_naver_real_estate_live_price(keyword):
    """네이버 부동산 단지 검색 후 중개업소 실매물 최저가 반환 (단위: 원)"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Referer": "https://m.land.naver.com/",
            "Accept": "application/json"
        }

        # ✅ 1단계: 자동완성 API로 단지 코드 획득
        search_url = f"https://completion.land.naver.com/ac?q={requests.utils.quote(keyword)}&re=1&vt=2"
        res = requests.get(search_url, headers=headers, timeout=5)

        if res.status_code != 200:
            return None

        data = res.json()
        items = data.get("items", [[]])[0]  # 첫 번째 결과 그룹
        if not items:
            return None

        # items[0] 구조: [단지명, 단지코드, 타입, ...]
        bldg_id = items[0][1] if len(items[0]) > 1 else None
        if not bldg_id:
            return None

        # ✅ 2단계: 단지 매물 리스트 조회 (최저가 정렬)
        articles_url = (
            f"https://m.land.naver.com/article/articleList"
            f"?rletTypeCd=A01&tradTpCd=A1&complexNo={bldg_id}&order=prc&page=1"
        )
        res2 = requests.get(articles_url, headers=headers, timeout=5)

        if res2.status_code != 200:
            return None

        article_data = res2.json()
        article_list = article_data.get("result", {}).get("list", [])

        if not article_list:
            return None

        # ✅ 3단계: 최저가 매물 가격 파싱 (네이버 단위: 만원)
        first_item = article_list[0]
        prc_raw = first_item.get("prc", 0)  # 예: 150000 (15억, 만원 단위)
        return int(prc_raw) * 10000  # 원화 변환

    except Exception as e:
        print(f"[Naver Crawler Error] {keyword}: {e}")
        return None

# ==========================================
# [CORE 1] 주식 엔진 파이프라인 (보존)
# ==========================================
@api_blueprint.route("/stock/search", methods=["GET"])
def search_stock():
    supabase = get_supabase()
    market = request.args.get("market", "KR")
    query = request.args.get("query", "").strip()
    if not query: 
        return jsonify([])

    try:
        # 🇺🇸 미국 시장은 기존 Finnhub 연동 파이프라인 유지 (성역)
        if market == "US":
            FINNHUB_KEY = os.getenv("FINNHUB_API_KEY") or os.getenv("FINNHUB_KEY")
            url = f"https://finnhub.io/api/v1/search?q={query}&token={FINNHUB_KEY}"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                results = response.json().get("result", [])
                return jsonify([
                    {"symbol": i.get("symbol", ""), "name": i.get("description", "")} 
                    for i in results[:10] if "." not in i.get("symbol", "")
                ])
            return jsonify([])
        
        # 🇰🇷 한국 시장: 외부 네이버 API 폐기 ➔ 오직 우리가 약속한 Supabase 테이블에서만 추출
        else:
            if not supabase:
                print("❌ [Search Engine] Supabase 클라이언트가 초기화되지 않았습니다.")
                return jsonify([])
                
            # 💡 [정밀 쿼리] 종목명(name) 또는 티커코드(symbol) 둘 중 하나만 매칭되어도 잡히도록 or 조건 가드 적용
            # ilike 구문으로 대소문자 구분 없이 부분 일치 검색 수행
            res = supabase.table("kr_stock_list")\
                .select("symbol, name")\
                .or_(f"name.ilike.%{query}%,symbol.ilike.%{query}%")\
                .limit(10)\
                .execute()
                
            output = []
            if res.data:
                for item in res.data:
                    output.append({
                        "symbol": str(item.get("symbol", "")).strip(),
                        "name": str(item.get("name", "")).strip()
                    })
                    
            return jsonify(output)

    except Exception as e:
        print(f"❌ [Search Engine] Supabase 주식 검색 컨트롤러 치명적 예외 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify([])
    
@api_blueprint.route("/portfolio", methods=["GET"])
def get_portfolio():
    supabase = get_supabase()
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
    portfolio = {"KR": [], "US": []}
    total_eval_krw, total_pur_krw, total_eval_usd, total_pur_usd = 0, 0, 0, 0

    for stock in db_stocks:
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
            market = stock.get("market", "KR")
            symbol = stock.get("symbol", "")
            if qty <= 0: continue

            stock_data = {
                "id": stock.get("id"), "symbol": symbol, "name": stock.get("name") or symbol, "market": market,
                "quantity": qty, "avg_price": avg_p, "current_price": avg_p, "chg_percent": 0.0,
                "purchase_amount": 0, "eval_amount": 0, "total_profit": 0, "total_profit_percent": 0.0, "weight_percent": 0.0
            }
            if market == "US":
                rt = UsStockService.get_realtime_price(symbol)
                stock_data["purchase_amount"] = round(avg_p * qty, 2)
                if rt: 
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                    stock_data["chg_percent"] = float(rt.get("chg_percent", 0.0))
                stock_data["eval_amount"] = round(stock_data["current_price"] * qty, 2)
                stock_data["total_profit"] = round(stock_data["eval_amount"] - stock_data["purchase_amount"], 2)
                if stock_data["purchase_amount"] > 0: stock_data["total_profit_percent"] = round((stock_data["total_profit"] / stock_data["purchase_amount"]) * 100, 2)
                total_pur_usd += stock_data["purchase_amount"]; total_eval_usd += stock_data["eval_amount"]
            else:
                rt = KrStockService.get_realtime_price(symbol)
                stock_data["purchase_amount"] = int(avg_p * qty)
                if rt: 
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                    stock_data["chg_percent"] = float(rt.get("chg_percent", 0.0))
                stock_data["eval_amount"] = int(stock_data["current_price"] * qty)
                stock_data["total_profit"] = stock_data["eval_amount"] - stock_data["purchase_amount"]
                if stock_data["purchase_amount"] > 0: stock_data["total_profit_percent"] = round((stock_data["total_profit"] / stock_data["purchase_amount"]) * 100, 2)
                total_pur_krw += stock_data["purchase_amount"]; total_eval_krw += stock_data["eval_amount"]
            portfolio[market].append(stock_data)
        except Exception: continue

    combined_total_krw = total_eval_krw + int(total_eval_usd * exchange_rate)
    if combined_total_krw > 0:
        for m in ["KR", "US"]:
            for s in portfolio[m]:
                eval_krw = (s["eval_amount"] * exchange_rate) if m == "US" else s["eval_amount"]
                s["weight_percent"] = round((eval_krw / combined_total_krw) * 100, 1)

    return jsonify({
        "combined_total_krw": combined_total_krw, "exchange_rate": exchange_rate,
        "profit_rate_krw": round(((total_eval_krw - total_pur_krw) / total_pur_krw * 100), 2) if total_pur_krw > 0 else 0.0,
        "profit_rate_usd": round(((total_eval_usd - total_pur_usd) / total_pur_usd * 100), 2) if total_pur_usd > 0 else 0.0,
        "total_evaluation_krw": int(total_eval_krw), "total_evaluation_usd": round(total_eval_usd, 2), "portfolio": portfolio
    })

@api_blueprint.route("/portfolio/save", methods=["POST"])
def save_portfolio():
    supabase = get_supabase()
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    data = request.get_json()
    symbol, tx_type = data.get("symbol"), data.get("tx_type", "BUY")
    if not symbol: return jsonify({"status": "error", "message": "종목 코드가 누락되었습니다."}), 400

    try:
        if tx_type == "DELETE":
            supabase.table("stock_portfolio").delete().eq("symbol", symbol).execute()
            return jsonify({"status": "success"})
        # BUY/SELL 로직 축약 보존
        existing = supabase.table("stock_portfolio").select("*").eq("symbol", symbol).execute()
        if existing.data and len(existing.data) > 0:
            current_stock = existing.data[0]
            old_qty = float(current_stock.get("quantity", 0) or 0)
            old_price = float(current_stock.get("avg_price", 0) or 0)
            if tx_type == "BUY":
                new_qty = old_qty + float(data.get("quantity", 0))
                new_price = ((old_price * old_qty) + (float(data.get("avg_price", 0)) * float(data.get("quantity", 0)))) / new_qty
                supabase.table("stock_portfolio").update({"quantity": new_qty, "avg_price": int(new_price)}).eq("symbol", symbol).execute()
        else:
            supabase.table("stock_portfolio").insert({"market": data.get("market"), "symbol": symbol, "name": data.get("name"), "quantity": float(data.get("quantity", 0)), "avg_price": float(data.get("avg_price", 0))}).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# [CORE 2] 부동산 엔진 파이프라인 (실매물 실시간 조회 엔진 업그레이드)
# ==========================================
@api_blueprint.route("/real-estate", methods=["GET"])
def get_real_estate():
    supabase = get_supabase()
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    try:
        res = supabase.table("real_estate_portfolio").select("*").order("created_at").execute()
        db_estates = res.data if res.data else []
        
        holding_assets = []
        watch_assets = []
        total_eval_re, total_debt_re, net_lease_cash = 0, 0, 0 

        for item in db_estates:
            raw = item.get("is_watchlist")
            is_watch = raw is True or str(raw).lower() == "true"
            h_type = item.get("holding_type", "OWN")
            name = item.get("name")
            
            c_price = float(item.get("current_price", 0) or 0)
            debt = float(item.get("debt", 0) or 0)
            monthly_rent = float(item.get("monthly_rent", 0) or 0)
            purchase_price = float(item.get("purchase_price", 0) or 0)

            # 💡 [핵심 엔진] 만약 관심 부동산 그룹이라면 네이버 실시간 매물 최저가를 즉시 크롤링해서 동기화합니다.
            if is_watch:
                live_price = get_naver_real_estate_live_price(name)
                if live_price:
                    c_price = live_price # 실매물가로 런타임 강제 치환
                    # 백엔드 DB에도 동적 캐싱 업데이트 실행
                    supabase.table("real_estate_portfolio").update({"current_price": live_price}).eq("name", name).execute()

            if h_type == "TENANT_LEASE":
                computed_eval = 0 
                computed_debt = debt
                net_lease_cash += (monthly_rent - debt)
            elif h_type == "LEASE":
                computed_eval = c_price
                computed_debt = debt
                net_lease_cash += (c_price - debt - monthly_rent)
            else:
                computed_eval = c_price
                computed_debt = debt

            estate_data = {
                "id": item.get("id"), "name": name, "estate_type": item.get("estate_type"), "holding_type": h_type,
                "purchase_price": purchase_price, "current_price": c_price, "debt": debt, "monthly_rent": monthly_rent,
                "is_watchlist": is_watch, "target_price": float(item.get("target_price", 0) or 0) 
            }

            if is_watch:
                watch_assets.append(estate_data) # 관심부동산 레이어로 이격 분류 
            else:
                holding_assets.append(estate_data)
                total_eval_re += computed_eval
                total_debt_re += computed_debt

        return jsonify({
            "total_evaluation_re": total_eval_re, "total_debt_re": total_debt_re, "net_worth_re": total_eval_re - total_debt_re,
            "net_lease_cash": net_lease_cash, "holding_assets": holding_assets, "watch_assets": watch_assets 
        })
    except Exception as e: return jsonify({"status": "error", "message": f"부동산 로드 실패: {str(e)}"}), 500

@api_blueprint.route("/real-estate/save", methods=["POST"])
def save_real_estate():
    supabase = get_supabase()
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    try:
        data = request.get_json()
        if data.get("action") == "DELETE":
            asset_id = data.get("id")
            if asset_id: supabase.table("real_estate_portfolio").delete().eq("id", asset_id).execute()
            return jsonify({"status": "success"})

        name = data.get("name")
        payload = {
            "name": name, "estate_type": data.get("estate_type"),
            "holding_type": "WATCHLIST" if bool(data.get("is_watchlist")) else data.get("holding_type", "OWN"),
            "purchase_price": float(data.get("purchase_price") or 0),
            "current_price": float(data.get("current_price") or 0),
            "debt": float(data.get("debt") or 0),
            "monthly_rent": float(data.get("monthly_rent") or 0),
            "is_watchlist": str(data.get("is_watchlist")).lower() == "true",
            "target_price": float(data.get("target_price") or 0) 
        }

        existing = supabase.table("real_estate_portfolio").select("id").eq("name", name).execute()
        if existing.data and len(existing.data) > 0:
            supabase.table("real_estate_portfolio").update(payload).eq("name", name).execute()
        else:
            supabase.table("real_estate_portfolio").insert(payload).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================
# [신규 기능] 네이버 부동산 공식 백본망 기반 단지 검색 API
# ==========================================
@api_blueprint.route("/real-estate/search", methods=["GET"])
def search_real_estate():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify([])
    try:
        url = f"https://completion.land.naver.com/ac?q={requests.utils.quote(query)}&re=1&vt=2"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
            "Referer": "https://m.land.naver.com/",
            "Accept": "application/json"
        }
        res = requests.get(url, headers=headers, timeout=5)

        # ✅ 디버깅 - 실제 응답 구조를 그대로 찍는다
        print(f"[RE-SEARCH DEBUG] status={res.status_code}")
        print(f"[RE-SEARCH DEBUG] raw={res.text[:1000]}")

        if res.status_code != 200:
            return jsonify([])

        raw = res.json()
        items_group = raw.get("items", [])
        output = []

        if items_group and len(items_group) > 0:
            for item in items_group[0][:10]:
                print(f"[RE-SEARCH DEBUG] item={item}")  # ✅ 각 item의 실제 구조 출력
                output.append({"raw_item": item})  # 일단 원본 그대로 반환해서 확인

        return jsonify(output)
    except Exception as e:
        print(f"❌ 부동산 검색 엔드포인트 예외: {str(e)}")
        return jsonify([])