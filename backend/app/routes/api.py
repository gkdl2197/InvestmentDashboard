import os
import requests
from flask import Blueprint, jsonify, request
from supabase import create_client, Client
from backend.app.services.exchange_rate import ExchangeRateService
from backend.app.services.us_stock import UsStockService
from backend.app.services.kr_stock import KrStockService
from backend.app.config import Config

api_blueprint = Blueprint('api', __name__, url_prefix='/api')

# 🌐 Supabase 클라우드 클라이언트 초기화
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

@api_blueprint.route("/portfolio", methods=["GET"])
def get_portfolio():
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500

    db_stocks = []
    realized_amount = 0
    realized_rate = 0.0
    
    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
        
        r_res = supabase.table("realized_profit").select("*").eq("id", 1).execute()
        if r_res.data and len(r_res.data) > 0: 
            realized_amount = int(r_res.data[0].get("amount", 0) or 0)
            realized_rate = float(r_res.data[0].get("rate", 0.0) or 0.0)
    except Exception as e:
        return jsonify({"status": "error", "message": f"DB 로드 치명적 에러: {str(e)}"}), 500

    exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
    portfolio = {"KR": [], "US": []}
    total_evaluation_krw = 0     

    for stock in db_stocks:
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
            market = stock.get("market", "KR")
            symbol = stock.get("symbol", "")
            
            # 💡 [화폐 규격 분리] 시장별 독립 딕셔너리 빌드
            stock_data = {
                "id": stock.get("id"), "symbol": symbol, "name": stock.get("name") or symbol,
                "quantity": qty, "avg_price": avg_p, "current_price": avg_p, "chg_percent": 0.0,
                "purchase_amount": 0, "eval_amount": 0, "total_profit": 0,
                "total_profit_percent": 0.0, "weight_percent": 0.0, "market": market
            }
            
            if market == "US":
                # 🇺🇸 미국 주식: 모든 재무 단위를 순수 달러($)로 계산 및 유지
                rt = UsStockService.get_realtime_price(symbol)
                stock_data["purchase_amount"] = round(avg_p * qty, 2)
                if rt:
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                    stock_data["chg_percent"] = float(rt.get("chg_percent", 0.0))
                stock_data["eval_amount"] = round(stock_data["current_price"] * qty, 2)
                stock_data["total_profit"] = round(stock_data["eval_amount"] - stock_data["purchase_amount"], 2)
                
                if stock_data["purchase_amount"] > 0:
                    stock_data["total_profit_percent"] = round((stock_data["total_profit"] / stock_data["purchase_amount"]) * 100, 2)
                
                # 전체 포트폴리오 비중 계산용 총 원화 합산 가드만 유지
                total_evaluation_krw += int(stock_data["eval_amount"] * exchange_rate)
            else:
                # 🇰🇷 한국 주식: 기존 원화(₩) 체계 유지
                rt = KrStockService.get_realtime_price(symbol)
                stock_data["purchase_amount"] = int(avg_p * qty)
                if rt:
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                    stock_data["chg_percent"] = float(rt.get("chg_percent", 0.0))
                stock_data["eval_amount"] = int(stock_data["current_price"] * qty)
                stock_data["total_profit"] = stock_data["eval_amount"] - stock_data["purchase_amount"]
                
                if stock_data["purchase_amount"] > 0:
                    stock_data["total_profit_percent"] = round((stock_data["total_profit"] / stock_data["purchase_amount"]) * 100, 2)
                
                total_evaluation_krw += stock_data["eval_amount"]

            portfolio[market].append(stock_data)
        except Exception:
            continue

    # 📊 비중(Weight) 재계산 (원화 환산 가치 기준 비중 설정)
    if total_evaluation_krw > 0:
        for m in ["KR", "US"]:
            for s in portfolio[m]:
                eval_krw = (s["eval_amount"] * exchange_rate) if m == "US" else s["eval_amount"]
                s["weight_percent"] = round((eval_krw / total_evaluation_krw) * 100, 1)

    return jsonify({
        "total_evaluation": int(total_evaluation_krw),
        "realized_profit": realized_amount,
        "realized_rate": round(realized_rate, 2), 
        "exchange_rate": exchange_rate, 
        "portfolio": portfolio
    })

@api_blueprint.route("/stock/search", methods=["GET"])
def search_stock():
    market = request.args.get("market")
    query = request.args.get("query", "").strip()
    if not query: return jsonify([])
    
    results = []
    
    if market == "KR":
        # 💡 [구조 대혁신] 네이버 연동 전면 폐기 -> 우리 Supabase 인덱싱 테이블에서 ilike 검색
        try:
            res = supabase.table("kr_stock_list") \
                .select("symbol, name") \
                .ilike("name", f"%{query}%") \
                .limit(8) \
                .execute()
                
            if res.data:
                for item in res.data:
                    results.append({"symbol": item.get("symbol"), "name": item.get("name")})
        except Exception as e:
            print(f"❌ 국내 Supabase 자체 자동검색 쿼리 실패: {e}")
            
    elif market == "US":
        api_key = Config.FINNHUB_API_KEY
        url = f"https://finnhub.io/api/v1/search?q={query}&token={api_key}"
        try:
            res = requests.get(url, timeout=5).json()
            if "result" in res and isinstance(res["result"], list):
                for item in res["result"][:6]:
                    results.append({"symbol": item.get("symbol", ""), "name": item.get("description", "")})
        except Exception: pass
            
    return jsonify(results[:8])

@api_blueprint.route("/portfolio/save", methods=["POST"])
def save_stock():
    data = request.json or {}
    action = data.get("action")
    market = data.get("market")
    name = data.get("name", "").strip()
    target_symbol = data.get("symbol", "").strip().upper()
    
    try: quantity = float(data.get("quantity") or 0)
    except Exception: quantity = 0.0
    try: avg_price = float(data.get("avg_price") or 0)
    except Exception: avg_price = 0.0

    # 💡 [매도 연산 매칭 엔진 완벽 교정]
    if action in ["sell_all", "sell_part"]:
        try:
            exist_res = None
            # 1. 심볼 코드가 넘어온 경우 심볼로 1차 매칭
            if target_symbol:
                exist_res = supabase.table("stock_portfolio").select("*").eq("symbol", target_symbol).execute()
            
            # 2. 심볼로 조회가 안 되거나 심볼이 없을 경우 이름으로 유연하게 가드 검색
            if (not exist_res or not exist_res.data) and name:
                exist_res = supabase.table("stock_portfolio").select("*").eq("name", name).execute()
                
            if exist_res and exist_res.data:
                target_record = exist_res.data[0]
                eqty = float(target_record.get("quantity") or 0)
                eavg = float(target_record.get("avg_price") or 0)
                emarket = target_record.get("market", "KR")
                
                sell_qty = eqty if action == "sell_all" else quantity
                calc_price = avg_price if avg_price > 0 else eavg
                exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
                
                if emarket == "KR":
                    purchase_sub = int(eavg * sell_qty)
                    sell_sub = int(calc_price * sell_qty)
                else:
                    purchase_sub = int(eavg * sell_qty * exchange_rate)
                    sell_sub = int(calc_price * sell_qty * exchange_rate)
                    
                profit_krw = sell_sub - purchase_sub
                
                # 실현손익 테이블(realized_profit) 누적 및 연동 계산 보수
                try:
                    cur_realized = supabase.table("realized_profit").select("*").eq("id", 1).execute()
                    if cur_realized.data:
                        old_amt = int(cur_realized.data[0].get("amount", 0) or 0)
                        new_amt = old_amt + profit_krw
                        new_rate = round((profit_krw / purchase_sub) * 100, 2) if purchase_sub > 0 else 0.0
                        
                        supabase.table("realized_profit").update({"amount": new_amt, "rate": new_rate}).eq("id", 1).execute()
                    else:
                        new_rate = round((profit_krw / purchase_sub) * 100, 2) if purchase_sub > 0 else 0.0
                        supabase.table("realized_profit").insert({"id": 1, "amount": profit_krw, "rate": new_rate}).execute()
                except Exception as ex:
                    print(f"⚠️ 실현손익 테이블 처리 실패: {ex}")

                # 잔고 수량 제어 처리
                if action == "sell_all":
                    supabase.table("stock_portfolio").delete().eq("id", target_record["id"]).execute()
                    return jsonify({"status": "success", "message": f"[{name or target_symbol}] 전량 매도 및 확정 실현손익 정산 완료."})
                elif action == "sell_part":
                    new_qty = eqty - quantity
                    if new_qty <= 0:
                        supabase.table("stock_portfolio").delete().eq("id", target_record["id"]).execute()
                    else:
                        supabase.table("stock_portfolio").update({"quantity": new_qty}).eq("id", target_record["id"]).execute()
                    return jsonify({"status": "success", "message": f"[{name or target_symbol}] 부분 매도 및 확정 실현손익 반영 완료."})
            else:
                return jsonify({"status": "error", "message": f"보유 자산 목록에서 [{name or target_symbol}] 종목을 매칭하지 못했습니다. 입력값을 확인해 주세요."}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # 매수 로직부 기동 가드 유지
    if not market or not name: return jsonify({"status": "error", "message": "필수값 누락"}), 400

    if not target_symbol:
        if market == "KR":
            url = f"https://ac.stock.naver.com/ac?q={name}&target=stock"
            try:
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3).json()
                items = res.get("items", [])
                if items and isinstance(items, list) and items[0]:
                    sub = items[0] if isinstance(items[0], list) else items
                    if sub: target_symbol = str(sub[0][0]) if isinstance(sub[0], list) else str(sub[0].get("code", ""))
            except Exception: pass
        elif market == "US":
            api_key = Config.FINNHUB_API_KEY
            url = f"https://finnhub.io/api/v1/search?q={name}&token={api_key}"
            try:
                res = requests.get(url, timeout=3).json()
                if "result" in res and res["result"]: target_symbol = res["result"][0].get("symbol", "")
            except Exception: pass

    if not target_symbol: target_symbol = name.upper()

    try:
        check_exist = supabase.table("stock_portfolio").select("*").eq("symbol", target_symbol).execute()
        existing_stock = check_exist.data[0] if check_exist.data else None
    except Exception: existing_stock = None

    if action in ["new_buy", "add_buy"]:
        if existing_stock:
            ext_qty = float(existing_stock.get("quantity") or 0)
            ext_price = float(existing_stock.get("avg_price") or 0)
            total_cost = (ext_qty * ext_price) + (quantity * avg_price)
            new_qty = ext_qty + quantity
            new_avg = round(total_cost / new_qty, 2) if new_qty > 0 else avg_price
            supabase.table("stock_portfolio").update({"quantity": new_qty, "avg_price": new_avg, "name": name}).eq("id", existing_stock["id"]).execute()
            message = f"[{name}] 매수 반영 완료. (평단가: ₩{new_avg})"
        else:
            supabase.table("stock_portfolio").insert({"market": market, "symbol": target_symbol, "name": name, "quantity": quantity, "avg_price": avg_price}).execute()
            message = f"[{name}] 신규 종목 등록 완료."

    return jsonify({"status": "success", "message": message})