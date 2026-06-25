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
    if not supabase:
        return jsonify({"status": "error", "message": "Supabase 설정 누락"}), 500

    db_stocks = []
    realized_amount = 0
    
    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
    except Exception as e:
        print(f"❌ 포트폴리오 DB 로드 실패: {e}")
        db_stocks = []
        
    try:
        realized_res = supabase.table("realized_profit").select("amount").eq("id", 1).execute()
        if realized_res.data and len(realized_res.data) > 0:
            realized_amount = int(realized_res.data[0].get("amount", 0) or 0)
    except Exception as e:
        print(f"❌ 실현손익 로드 실패: {e}")
        realized_amount = 0

    try:
        exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
    except Exception:
        exchange_rate = 1350.0

    portfolio = {"KR": [], "US": []}
    total_purchase = 0       
    total_evaluation = 0     
    total_today_profit = 0   

    for stock in db_stocks:
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
            
            stock_data = {
                "id": stock.get("id"),
                "symbol": stock.get("symbol", ""),
                "name": stock.get("name") or stock.get("symbol", ""),
                "quantity": qty,
                "avg_price": avg_p,
                "current_price": avg_p,  
                "chg_percent": 0.0,
                "purchase_amount_krw": 0,
                "eval_amount_krw": 0,
                "total_profit_krw": 0,
                "total_profit_percent": 0.0,
                "weight_percent": 0.0,
                "market": stock.get("market", "KR")
            }
            
            market = stock_data["market"]
            today_profit_krw = 0
            
            if market == "US":
                try:
                    realtime = UsStockService.get_realtime_price(stock_data["symbol"])
                    if realtime and isinstance(realtime, dict):
                        stock_data["current_price"] = float(realtime.get("current_price") or avg_p)
                        stock_data["chg_percent"] = float(realtime.get("chg_percent") or 0.0)
                except Exception:
                    pass
                
                stock_data["purchase_amount_krw"] = int(avg_p * qty * exchange_rate)
                stock_data["eval_amount_krw"] = int(stock_data["current_price"] * qty * exchange_rate)
                
                pct = stock_data["chg_percent"]
                prev_price = stock_data["current_price"] / (1 + (pct / 100)) if pct != -100 else stock_data["current_price"]
                today_profit_krw = (stock_data["current_price"] - prev_price) * qty * exchange_rate
                
                stock_data["total_profit_krw"] = stock_data["eval_amount_krw"] - stock_data["purchase_amount_krw"]
                if stock_data["purchase_amount_krw"] > 0:
                    stock_data["total_profit_percent"] = round((stock_data["total_profit_krw"] / stock_data["purchase_amount_krw"]) * 100, 2)
                
                portfolio["US"].append(stock_data)
                
            else: # KR
                try:
                    realtime = KrStockService.get_realtime_price(stock_data["symbol"])
                    if realtime and isinstance(realtime, dict):
                        stock_data["current_price"] = float(realtime.get("current_price") or avg_p)
                        stock_data["chg_percent"] = float(realtime.get("chg_percent") or 0.0)
                except Exception:
                    pass
                    
                stock_data["purchase_amount_krw"] = int(avg_p * qty)
                stock_data["eval_amount_krw"] = int(stock_data["current_price"] * qty)
                
                pct = stock_data["chg_percent"]
                prev_price = stock_data["current_price"] / (1 + (pct / 100)) if pct != -100 else stock_data["current_price"]
                today_profit_krw = (stock_data["current_price"] - prev_price) * qty
                
                stock_data["total_profit_krw"] = stock_data["eval_amount_krw"] - stock_data["purchase_amount_krw"]
                if stock_data["purchase_amount_krw"] > 0:
                    stock_data["total_profit_percent"] = round((stock_data["total_profit_krw"] / stock_data["purchase_amount_krw"]) * 100, 2)
                
                portfolio["KR"].append(stock_data)

            total_purchase += stock_data["purchase_amount_krw"]
            total_evaluation += stock_data["eval_amount_krw"]
            total_today_profit += today_profit_krw
        except Exception as e:
            print(f"❌ 개별 종목 파싱 가드 작동: {e}")
            continue

    if total_evaluation > 0:
        for m in ["US", "KR"]:
            for stock in portfolio[m]:
                stock["weight_percent"] = round((stock["eval_amount_krw"] / total_evaluation) * 100, 1)

    total_profit = total_evaluation - total_purchase
    total_profit_percent = (total_profit / total_purchase * 100) if total_purchase > 0 else 0.0

    return jsonify({
        "total_evaluation": int(total_evaluation),
        "total_profit": int(total_profit),
        "total_profit_percent": round(total_profit_percent, 2),
        "total_today_profit": int(total_today_profit),
        "realized_profit": realized_amount,
        "exchange_rate": exchange_rate,
        "portfolio": portfolio
    })


@api_blueprint.route("/stock/search", methods=["GET"])
def search_stock():
    market = request.args.get("market")
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify([])
    
    results = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Referer': 'https://finance.naver.com'
    }
    
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
                        elif isinstance(item, dict):
                            sym = item.get("code") or item.get("symbol") or item.get("id") or ""
                            nm = item.get("name") or item.get("title") or ""
                            if sym and nm:
                                results.append({"symbol": str(sym), "name": str(nm)})
        except Exception as e:
            print(f"❌ 국내 자동검색 실패: {e}")
            
    elif market == "US":
        api_key = Config.FINNHUB_API_KEY
        url = f"https://finnhub.io/api/v1/search?q={query}&token={api_key}"
        try:
            res = requests.get(url, timeout=5).json()
            if "result" in res and isinstance(res["result"], list):
                for item in res["result"][:6]:
                    results.append({
                        "symbol": item.get("symbol", ""), 
                        "name": item.get("description", item.get("symbol", ""))
                    })
        except Exception as e:
            print(f"❌ 미국 자동검색 실패: {e}")
            
    return jsonify(results[:8])


@api_blueprint.route("/portfolio/save", methods=["POST"])
def save_stock():
    data = request.json or {}
    action = data.get("action")
    market = data.get("market")
    name = data.get("name", "").strip()
    
    # 💡 형변환 가드 강화 (공백이 들어오면 에러 내지 말고 0 처리)
    try:
        quantity = float(data.get("quantity") or 0)
    except Exception:
        quantity = 0.0
        
    try:
        avg_price = float(data.get("avg_price") or 0)
    except Exception:
        avg_price = 0.0
        
    stock_id = data.get("id")

    if not action:
        return jsonify({"status": "error", "message": "액션 구분이 누락되었습니다."}), 400

    if action == "sell_all" or action == "delete":
        target_symbol = data.get("symbol")
        if stock_id and not target_symbol:
            try:
                target_stock = supabase.table("stock_portfolio").select("*").eq("id", stock_id).execute()
                if target_stock.data:
                    target_symbol = target_stock.data[0].get("symbol")
                    market = target_stock.data[0].get("market")
                    name = target_stock.data[0].get("name")
            except Exception: pass
        
        if not target_symbol and name:
            target_symbol = name
            
        try:
            exist_res = supabase.table("stock_portfolio").select("*").eq("symbol", target_symbol).execute()
            if exist_res.data:
                eqty = float(exist_res.data[0].get("quantity") or 0)
                eavg = float(exist_res.data[0].get("avg_price") or 0)
                
                curr_p = eavg
                exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
                if market == "KR":
                    rt = KrStockService.get_realtime_price(target_symbol)
                    if rt: curr_p = float(rt.get("current_price", eavg))
                    profit_krw = int((curr_p - eavg) * eqty)
                else:
                    rt = UsStockService.get_realtime_price(target_symbol)
                    if rt: curr_p = float(rt.get("current_price", eavg))
                    profit_krw = int((curr_p - eavg) * eqty * exchange_rate)
                
                try:
                    cur_realized = supabase.table("realized_profit").select("amount").eq("id", 1).execute()
                    old_amt = int(cur_realized.data[0]["amount"]) if cur_realized.data else 0
                    supabase.table("realized_profit").update({"amount": old_amt + profit_krw}).eq("id", 1).execute()
                except Exception: pass

            if stock_id:
                supabase.table("stock_portfolio").delete().eq("id", stock_id).execute()
            else:
                supabase.table("stock_portfolio").delete().eq("symbol", target_symbol).execute()
                
            return jsonify({"status": "success", "message": f"[{name or target_symbol}] 전량 매도 및 실현손익 정산 완료."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if not market or not name:
        return jsonify({"status": "error", "message": "시장 및 종목명이 누락되었습니다."}), 400

    symbol = data.get("symbol", "").strip().upper()
    
    # 💡 [핵심 수술 마감] 버튼 타격 시 실시간 다차원 코드 자동 포획 엔진 장착 (인덱스 에러 철통방어)
    if not symbol:
        if market == "KR":
            url = f"https://ac.stock.naver.com/ac?q={name}&target=stock"
            try:
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3).json()
                items = res.get("items", [])
                if items and isinstance(items, list):
                    for sub in items:
                        if not sub: continue
                        target_list = sub if isinstance(sub, list) else [sub]
                        if target_list and len(target_list) > 0:
                            first = target_list[0]
                            if isinstance(first, list) and len(first) >= 2:
                                symbol = str(first[0])
                                break
                            elif isinstance(first, dict):
                                symbol = str(first.get("code") or first.get("symbol") or "")
                                break
            except Exception: pass
        elif market == "US":
            api_key = Config.FINNHUB_API_KEY
            url = f"https://finnhub.io/api/v1/search?q={name}&token={api_key}"
            try:
                res = requests.get(url, timeout=3).json()
                if "result" in res and res["result"]:
                    symbol = res["result"][0].get("symbol", "")
            except Exception: pass

    if not symbol:
        symbol = name.upper()

    try:
        check_exist = supabase.table("stock_portfolio").select("*").eq("symbol", symbol).execute()
        existing_stock = check_exist.data[0] if check_exist.data else None
    except Exception:
        existing_stock = None

    if action in ["new_buy", "add_buy"]:
        if existing_stock:
            ext_qty = float(existing_stock.get("quantity") or 0)
            ext_price = float(existing_stock.get("avg_price") or 0)
            total_cost = (ext_qty * ext_price) + (quantity * avg_price)
            new_qty = ext_qty + quantity
            new_avg = round(total_cost / new_qty, 2) if new_qty > 0 else avg_price
            supabase.table("stock_portfolio").update({"quantity": new_qty, "avg_price": new_avg, "name": name}).eq("id", existing_stock["id"]).execute()
            message = f"[{name}] 매수 반영 완료. (합산 평단가: ₩{new_avg})"
        else:
            supabase.table("stock_portfolio").insert({"market": market, "symbol": symbol, "name": name, "quantity": quantity, "avg_price": avg_price}).execute()
            message = f"[{name}] 신규 종목 등록 완료."

    elif action == "sell_part":
        if not existing_stock:
            return jsonify({"status": "error", "message": "보유하지 않은 종목은 매도할 수 없습니다."}), 400
        
        ext_qty = float(existing_stock.get("quantity") or 0)
        ext_price = float(existing_stock.get("avg_price") or 0)
        
        if ext_qty < quantity:
            return jsonify({"status": "error", "message": f"보유량({ext_qty}주)보다 매도량({quantity}주)이 많습니다."}), 400
        
        new_qty = ext_qty - quantity
        exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
        
        if market == "KR":
            profit_krw = int((avg_price - ext_price) * quantity)
        else:
            profit_krw = int((avg_price - ext_price) * quantity * exchange_rate)
            
        try:
            cur_realized = supabase.table("realized_profit").select("amount").eq("id", 1).execute()
            old_amt = int(cur_realized.data[0]["amount"]) if cur_realized.data else 0
            supabase.table("realized_profit").update({"amount": old_amt + profit_krw}).eq("id", 1).execute()
        except Exception: pass

        if new_qty <= 0:
            supabase.table("stock_portfolio").delete().eq("id", existing_stock["id"]).execute()
            message = f"[{name}] 전량 매도 정산되어 포트폴리오에서 삭제되었습니다."
        else:
            supabase.table("stock_portfolio").update({"quantity": new_qty}).eq("id", existing_stock["id"]).execute()
            message = f"[{name}] {quantity}주 부분 매도 처리 및 실현손익 반영 완료."

    return jsonify({"status": "success", "message": message})