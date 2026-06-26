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
        if r_res.data: 
            realized_amount = int(r_res.data[0].get("amount", 0) or 0)
            realized_rate = float(r_res.data[0].get("rate", 0.0) or 0.0)
    except Exception as e:
        print(f"❌ DB 로드 실패 가드: {e}")

    exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
    portfolio = {"KR": [], "US": []}
    total_purchase = 0       
    total_evaluation = 0     

    for stock in db_stocks:
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
            market = stock.get("market", "KR")
            symbol = stock.get("symbol", "")
            
            stock_data = {
                "id": stock.get("id"), "symbol": symbol, "name": stock.get("name") or symbol,
                "quantity": qty, "avg_price": avg_p, "current_price": avg_p, "chg_percent": 0.0,
                "purchase_amount_krw": 0, "eval_amount_krw": 0, "total_profit_krw": 0,
                "total_profit_percent": 0.0, "weight_percent": 0.0, "market": market
            }
            
            if market == "US":
                rt = UsStockService.get_realtime_price(symbol)
                stock_data["purchase_amount_krw"] = int(avg_p * qty * exchange_rate)
                if rt:
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                    stock_data["chg_percent"] = float(rt.get("chg_percent", 0.0))
                stock_data["eval_amount_krw"] = int(stock_data["current_price"] * qty * exchange_rate)
            else:
                rt = KrStockService.get_realtime_price(symbol)
                stock_data["purchase_amount_krw"] = int(avg_p * qty)
                if rt:
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                    stock_data["chg_percent"] = float(rt.get("chg_percent", 0.0))
                stock_data["eval_amount_krw"] = int(stock_data["current_price"] * qty)
            
            stock_data["total_profit_krw"] = stock_data["eval_amount_krw"] - stock_data["purchase_amount_krw"]
            if stock_data["purchase_amount_krw"] > 0:
                stock_data["total_profit_percent"] = round((stock_data["total_profit_krw"] / stock_data["purchase_amount_krw"]) * 100, 2)

            portfolio[market].append(stock_data)
            total_purchase += stock_data["purchase_amount_krw"]
            total_evaluation += stock_data["eval_amount_krw"]
        except Exception:
            continue

    if total_evaluation > 0:
        for m in ["KR", "US"]:
            for s in portfolio[m]:
                s["weight_percent"] = round((s["eval_amount_krw"] / total_evaluation) * 100, 1)

    return jsonify({
        "total_evaluation": int(total_evaluation),
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
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    if market == "KR":
        url = f"https://ac.stock.naver.com/ac?q={query}&target=stock"
        try:
            res = requests.get(url, headers=headers, timeout=5).json()
            items = res.get("items", [])
            if items and isinstance(items, list):
                for sub in items:
                    if not sub: continue
                    target_list = sub if isinstance(sub, list) else [sub]
                    for item in target_list:
                        if isinstance(item, list) and len(item) >= 2:
                            results.append({"symbol": str(item[0]), "name": str(item[1])})
        except Exception: pass
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