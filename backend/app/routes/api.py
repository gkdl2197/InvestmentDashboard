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

def get_molit_recent_price(bjd_code: str, apt_name: str):
    from datetime import datetime, timedelta

    SERVICE_KEY = os.getenv("MOLIT_API_KEY", "ed5eb4cbab5b22ea97fe39d5fbb5c3b0b27037c3bc5c1d43ed3e2f7e37d261ba")
    BASE_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

    lawd_cd = bjd_code[:5] if bjd_code and len(bjd_code) >= 5 else None
    if not lawd_cd:
        return None

    now = datetime.now()
    months_to_try = [
        (now - timedelta(days=30 * i)).strftime("%Y%m")
        for i in range(0, 4)
    ]

    for deal_ymd in months_to_try:
        try:
            params = {
                "serviceKey": SERVICE_KEY,
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ymd,
                "pageNo": 1,
                "numOfRows": 100,
                "_type": "json"
            }
            res = requests.get(BASE_URL, params=params, timeout=10)

            print(f"[MOLIT DEBUG] {apt_name} {deal_ymd} → HTTP {res.status_code}")

            if res.status_code != 200:
                continue

            data = res.json()
            body = data.get("response", {}).get("body", {})
            total_count = body.get("totalCount", 0)
            items = body.get("items", {})

            print(f"[MOLIT DEBUG] {apt_name} {deal_ymd} → totalCount={total_count}, items_type={type(items).__name__}, items_preview={str(items)[:300]}")

            if not items or items == "":
                continue

            item_list = items.get("item", [])
            if isinstance(item_list, dict):
                item_list = [item_list]
            if not item_list:
                continue

            clean_apt_name = apt_name.replace(" ", "")
            matched = []
            for item in item_list:
                item_apt = str(item.get("aptNm", "")).replace(" ", "")
                print(f"[MOLIT DEBUG] 비교: '{clean_apt_name}' vs '{item_apt}'")
                if clean_apt_name in item_apt or item_apt in clean_apt_name:
                    try:
                        price_str = str(item.get("dealAmount", "0")).replace(",", "")
                        price = int(price_str) * 10000
                        deal_year = str(item.get("dealYear", ""))
                        deal_month = str(item.get("dealMonth", "")).zfill(2)
                        deal_day = str(item.get("dealDay", "")).zfill(2)
                        matched.append({
                            "price": price,
                            "date": f"{deal_year}{deal_month}{deal_day}"
                        })
                    except Exception:
                        continue

            if matched:
                matched.sort(key=lambda x: x["date"], reverse=True)
                print(f"[MOLIT] {apt_name} → {deal_ymd} 최근거래가: {matched[0]['price']:,}원")
                return matched[0]["price"]
            else:
                print(f"[MOLIT DEBUG] {apt_name} {deal_ymd} → 매칭 실패. 법정동 내 단지목록: {[i.get('aptNm') for i in item_list[:10]]}")

        except Exception as e:
            print(f"[MOLIT Error] {apt_name} {deal_ymd}: {e}")
            continue

    print(f"[MOLIT] {apt_name}: 최근 4개월 내 거래 데이터 없음")
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
            deposit = float(item.get("deposit", 0) or 0) # 💡 보증금 로드 추가
        
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
                "deposit": deposit, # 💡 프론트엔드로 전달
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
    if not supabase:
        return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    try:
        data = request.get_json()
        if data.get("action") == "DELETE":
            asset_id = data.get("id")
            if asset_id:
                supabase.table("real_estate_portfolio").delete().eq("id", asset_id).execute()
            return jsonify({"status": "success"})

        name = data.get("name", "").strip()
        if not name:
            return jsonify({"status": "error", "message": "이름 누락"}), 400

        # [save_real_estate 함수 내부]
        payload = {
            "name": name,
            "estate_type": data.get("estate_type", "APT"),
            "holding_type": "WATCHLIST" if bool(data.get("is_watchlist")) else data.get("holding_type", "OWN"),
            
            # 💡 쉼표(,) 에러 방지 및 누락된 보증금(deposit) 항목 이식 완료!
            "purchase_price": float(str(data.get("purchase_price") or "0").replace(",", "")),
            "current_price": float(str(data.get("current_price") or "0").replace(",", "")),
            "debt": float(str(data.get("debt") or "0").replace(",", "")),
            "monthly_rent": float(str(data.get("monthly_rent") or "0").replace(",", "")),
            "deposit": float(str(data.get("deposit") or "0").replace(",", "")), 
            
            "is_watchlist": str(data.get("is_watchlist")).lower() == "true",
            "target_price": float(str(data.get("target_price") or "0").replace(",", "")),
            "bjd_code": data.get("bjd_code", ""),
            "complex_code": data.get("complex_code", ""),
            "area": round(float(str(data.get("area") or "0").replace(",", "")), 2)
        }

        existing = supabase.table("real_estate_portfolio").select("id").eq("name", name).execute()
        if existing.data and len(existing.data) > 0:
            supabase.table("real_estate_portfolio").update(payload).eq("name", name).execute()
        else:
            supabase.table("real_estate_portfolio").insert(payload).execute()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    # ==========================================
@api_blueprint.route("/real-estate/search", methods=["GET"])
def search_real_estate():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify([])
    
    supabase = get_supabase()
    if not supabase:
        return jsonify([])

    try:
        res = supabase.table("real_estate_complexes")\
            .select("complex_code, complex_name, sido, sigungu, dong, bjd_code")\
            .ilike("complex_name", f"%{query}%")\
            .limit(15)\
            .execute()

        output = []
        if res.data:
            for item in res.data:
                name = item.get("complex_name", "")
                sido = item.get("sido", "")
                sigungu = item.get("sigungu", "")
                dong = item.get("dong", "")
                region = f"{sido} {sigungu} {dong}".strip()

                output.append({
                    "complexNo": item.get("complex_code", ""),
                    "name": f"{name} ({region})" if region else name,
                    "rawName": name,
                    "bjdCode": item.get("bjd_code", "")
                })

        return jsonify(output)

    except Exception as e:
        print(f"❌ 부동산 검색(DB) 엔드포인트 예외: {str(e)}")
        return jsonify([])
    
import xml.etree.ElementTree as ET

# ======================================================================
# 🏢 [국토부 오픈API 연동 인프라 - 클로드 수석님 마감본 (2단계 & 3단계)]
# ======================================================================

@api_blueprint.route("/real-estate/areas", methods=["GET"])
def get_real_estate_areas():
    bjd_code = request.args.get("bjd_code", "").strip()
    complex_name = request.args.get("name", "").strip()
    
    if not bjd_code or not complex_name:
        return jsonify([])
        
    lawd_cd = bjd_code[:5] if bjd_code and len(bjd_code) >= 5 else None
    if not lawd_cd:
        return jsonify([])

    from datetime import datetime, timedelta
    import requests
    import xml.etree.ElementTree as ET

    now = datetime.now()
    # 💡 [핵심 1] 장부 스캔 기간을 3개월 ➔ 12개월(1년)로 대폭 확장! (가뭄 해소)
    months_to_try = [(now - timedelta(days=30 * i)).strftime("%Y%m") for i in range(0, 12)]
    
    SERVICE_KEY = "ed5eb4cbab5b22ea97fe39d5fbb5c3b0b27037c3bc5c1d43ed3e2f7e37d261ba"
    BASE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
    
    areas = set()
    
    # 💡 [핵심 2] '아파트', '주상복합' 등 국토부의 제멋대로 수식어를 원천 제거하여 순수 단지명만 추출
    noise_words = ["아파트", "주상복합", "단지", " "]
    clean_target = complex_name
    for word in noise_words:
        clean_target = clean_target.replace(word, "")
        
    # 예: '경희궁의아침 4단지' -> ['경희궁의아침', '4단지'] 토큰화
    tokens = [t for t in complex_name.split() if len(t) > 1 and t not in noise_words]

    for deal_ymd in months_to_try:
        try:
            full_url = f"{BASE_URL}?serviceKey={SERVICE_KEY}&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&pageNo=1&numOfRows=100"
            res = requests.get(full_url, timeout=8)
            if res.status_code != 200:
                continue
                
            root = ET.fromstring(res.content)
            for item in root.findall(".//item"):
                apt_nm_el = item.find("aptNm")
                area_el = item.find("excluUseAr")
                
                if apt_nm_el is not None and area_el is not None:
                    item_apt = str(apt_nm_el.text or "").replace(" ", "")
                    
                    # 💡 매칭 조건 유연화: 핵심 이름이 포함되거나 토큰 중 하나라도 걸리면 합격
                    is_match = False
                    if clean_target in item_apt or item_apt in clean_target:
                        is_match = True
                    elif tokens and any(token in item_apt for token in tokens):
                        is_match = True
                        
                    if is_match:
                        area_val = area_el.text
                        if area_val:
                            areas.add(round(float(str(area_val).replace(",", "")), 2))
        except Exception:
            continue
            
    return jsonify(sorted(list(areas)))


@api_blueprint.route("/real-estate/price", methods=["GET"])
def get_real_estate_price():
    bjd_code = request.args.get("bjd_code", "").strip()
    complex_name = request.args.get("name", "").strip()
    area = request.args.get("area", "0").strip()

    if not bjd_code or not complex_name:
        return jsonify({"found": False, "price": 0, "deal_date": ""})

    lawd_cd = bjd_code[:5] if len(bjd_code) >= 5 else None
    if not lawd_cd:
        return jsonify({"found": False, "price": 0, "deal_date": ""})

    try:
        area_float = float(area)
    except:
        area_float = 0.0

    SERVICE_KEY = "ed5eb4cbab5b22ea97fe39d5fbb5c3b0b27037c3bc5c1d43ed3e2f7e37d261ba"
    BASE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"

    from datetime import datetime, timedelta
    import requests
    import xml.etree.ElementTree as ET

    now = datetime.now()
    # 💡 [동기화 1] 시세 조회도 평형과 완벽히 똑같이 12개월 장부를 뒤집니다.
    months_to_try = [(now - timedelta(days=30 * i)).strftime("%Y%m") for i in range(0, 12)]
    
    # 💡 [동기화 2] 평형에서 썼던 '너그러운 단지명 필터' 동일 적용
    noise_words = ["아파트", "주상복합", "단지", " "]
    clean_target = complex_name
    for word in noise_words:
        clean_target = clean_target.replace(word, "")
    tokens = [t for t in complex_name.split() if len(t) > 1 and t not in noise_words]

    matched = []

    for deal_ymd in months_to_try:
        try:
            full_url = f"{BASE_URL}?serviceKey={SERVICE_KEY}&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&pageNo=1&numOfRows=100"
            res = requests.get(full_url, timeout=8)
            if res.status_code != 200:
                continue

            root = ET.fromstring(res.content)

            for item in root.findall(".//item"):
                item_apt = (item.findtext("aptNm") or "").replace(" ", "")
                
                # 💡 유연한 매칭
                is_match = False
                if clean_target in item_apt or item_apt in clean_target:
                    is_match = True
                elif tokens and any(token in item_apt for token in tokens):
                    is_match = True

                if not is_match:
                    continue

                # 💡 평형(면적) 오차범위 3㎡ 이내 필터링
                if area_float > 0:
                    try:
                        item_area = float((item.findtext("excluUseAr") or "0").replace(",", ""))
                        if abs(item_area - area_float) > 3:
                            continue
                    except:
                        continue

                try:
                    price = int((item.findtext("dealAmount") or "0").replace(",", "")) * 10000
                    year = (item.findtext("dealYear") or "").strip()
                    month = (item.findtext("dealMonth") or "").strip().zfill(2)
                    day = (item.findtext("dealDay") or "").strip().zfill(2)
                    matched.append({
                        "price": price,
                        "date": f"{year}{month}{day}",
                        "deal_date": f"{year}-{month}"
                    })
                except:
                    continue
        except Exception:
            continue

        # 💡 [핵심 최적화] 가장 최근 달(월)에서 거래를 하나라도 찾았다면, 
        # 더 옛날 장부는 뒤질 필요 없이 즉시 반복문을 종료하여 속도를 끌어올립니다.
        if matched:
            break 

    if matched:
        matched.sort(key=lambda x: x["date"], reverse=True)
        return jsonify({
            "found": True,
            "price": matched[0]["price"],
            "deal_date": matched[0]["deal_date"]
        })

    return jsonify({"found": False, "price": 0, "deal_date": ""})