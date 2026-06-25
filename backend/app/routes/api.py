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
        # 1. 포트폴리오 로드
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
        
        # 2. 💡 실현손익 테이블에서 누적 실현손익 로드
        realized_res = supabase.table("realized_profit").select("amount").eq("id", 1).execute()
        if realized_res.data:
            realized_amount = int(realized_res.data[0].get("amount", 0))
    except Exception as e:
        print(f"❌ 데이터 로드 실패: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    exchange_rate = ExchangeRateService().get_usd_krw()
    portfolio = {"KR": [], "US": []}
    total_purchase = 0       
    total_evaluation = 0     
    total_today_profit = 0   

    for stock in db_stocks:
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
            "market": stock.get("market", "KR") # 💡 프론트에 market 확실하게 보장
        }
        
        market = stock_data["market"]
        today_profit_krw = 0
        
        if market == "US":
            realtime = UsStockService.get_realtime_price(stock_data["symbol"])
            if realtime:
                stock_data["current_price"] = float(realtime.get("current_price", avg_p))
                stock_data["chg_percent"] = float(realtime.get("chg_percent", 0.0))
            
            stock_data["purchase_amount_krw"] = int(avg_p * qty * exchange_rate)
            stock_data["eval_amount_krw"] = int(stock_data["current_price"] * qty * exchange_rate)
            
            prev_price = stock_data["current_price"] / (1 + (stock_data["chg_percent"] / 100)) if stock_data["chg_percent"] != -100 else stock_data["current_price"]
            today_profit_krw = (stock_data["current_price"] - prev_price) * qty * exchange_rate
            portfolio["US"].append(stock_data)
            
        elif market == "KR":
            realtime = KrStockService.get_realtime_price(stock_data["symbol"])
            if realtime:
                stock_data["current_price"] = float(realtime.get("current_price", avg_p))
                stock_data["chg_percent"] = float(realtime.get("chg_percent", 0.0))
                
            stock_data["purchase_amount_krw"] = int(avg_p * qty)
            stock_data["eval_amount_krw"] = int(stock_data["current_price"] * qty)
            
            prev_price = stock_data["current_price"] / (1 + (stock_data["chg_percent"] / 100)) if stock_data["chg_percent"] != -100 else stock_data["current_price"]
            today_profit_krw = (stock_data["current_price"] - prev_price) * qty
            portfolio["KR"].append(stock_data)

        stock_data["total_profit_krw"] = stock_data["eval_amount_krw"] - stock_data["purchase_amount_krw"]
        if stock_data["purchase_amount_krw"] > 0:
            stock_data["total_profit_percent"] = round((stock_data["total_profit_krw"] / stock_data["purchase_amount_krw"]) * 100, 2)

        total_purchase += stock_data["purchase_amount_krw"]
        total_evaluation += stock_data["eval_amount_krw"]
        total_today_profit += today_profit_krw

    # 비중 계산
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
        "realized_profit": realized_amount, # 💡 실현 손익 데이터 하이웨이 개통
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
            # 💡 [2026 최종 네이버 다차원 구조 완전 정복]
            items = res.get("items", [])
            if items and isinstance(items, list):
                # 네이버의 중첩 배열(List inside List) 또는 단일 배열 대응 가드
                for sub in items:
                    if not sub:
                        continue
                    # 만약 데이터가 또 배열로 감싸져 있다면 한 껍질 더 벗깁니다.
                    target_list = sub if isinstance(sub, list) else [sub]
                    
                    for item in target_list:
                        if isinstance(item, list) and len(item) >= 2:
                            # 족보 구조 A: [ "005930", "삼성전자", ... ]
                            results.append({"symbol": str(item[0]), "name": str(item[1])})
                        elif isinstance(item, dict):
                            # 족보 구조 B: { "code": "005930", "name": "삼성전자" }
                            sym = item.get("code") or item.get("symbol") or item.get("id") or ""
                            nm = item.get("name") or item.get("title") or ""
                            if sym and nm:
                                results.append({"symbol": str(sym), "name": str(nm)})
        except Exception as e:
            print(f"❌ 국내 자동검색 특수 파싱 실패: {e}")
            
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
    action = data.get("action")  # 'new_buy', 'add_buy', 'sell_part', 'sell_all'
    market = data.get("market")
    name = data.get("name", "").strip()
    quantity = float(data.get("quantity") or 0)
    avg_price = float(data.get("avg_price") or 0)
    
    # UI에서 넘겨받은 단일 종목 ID (삭제용)
    stock_id = data.get("id")

    if not action:
        return jsonify({"status": "error", "message": "액션 구분이 누락되었습니다."}), 400

    # 1. 전량 매도 / 삭제 분기인 경우 즉시 처리
    if action == "sell_all" or action == "delete":
        target_symbol = data.get("symbol")
        
        # 만약 symbol이 안 넘어왔고 ID만 있다면 조회해서 복구
        if stock_id and not target_symbol:
            target_stock = supabase.table("stock_portfolio").select("*").eq("id", stock_id).execute()
            if target_stock.data:
                target_symbol = target_stock.data[0].get("symbol")
                market = target_stock.data[0].get("market")
                name = target_stock.data[0].get("name")
        
        if not target_symbol and name:
            target_symbol = name # fallback
            
        try:
            # 💡 [실현 손익 정산] 전량 매도 시 현재가 기준으로 실현 손익 정산 후 삭제
            exist_res = supabase.table("stock_portfolio").select("*").eq("symbol", target_symbol).execute()
            if exist_res.data:
                eqty = float(exist_res.data[0]["quantity"])
                eavg = float(exist_res.data[0]["avg_price"])
                
                # 실시간 가격 가져오기
                curr_p = eavg
                exchange_rate = ExchangeRateService().get_usd_krw()
                if market == "KR":
                    rt = KrStockService.get_realtime_price(target_symbol)
                    if rt: curr_p = float(rt.get("current_price", eavg))
                    profit_krw = int((curr_p - eavg) * eqty)
                else:
                    rt = UsStockService.get_realtime_price(target_symbol)
                    if rt: curr_p = float(rt.get("current_price", eavg))
                    profit_krw = int((curr_p - eavg) * eqty * exchange_rate)
                
                # 기존 실현 손익 누적 반영
                cur_realized = supabase.table("realized_profit").select("amount").eq("id", 1).execute()
                old_amt = int(cur_realized.data[0]["amount"]) if cur_realized.data else 0
                supabase.table("realized_profit").update({"amount": old_amt + profit_krw}).eq("id", 1).execute()

            if stock_id:
                supabase.table("stock_portfolio").delete().eq("id", stock_id).execute()
            else:
                supabase.table("stock_portfolio").delete().eq("symbol", target_symbol).execute()
                
            return jsonify({"status": "success", "message": f"[{name or target_symbol}] 전량 매도 및 실현손익 정산 완료."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # 2. 일반 매수/매도 검증
    if not market or not name:
        return jsonify({"status": "error", "message": "시장 및 종목명이 누락되었습니다."}), 400

    # 종목 코드 포획 엔진
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        if market == "KR":
            url = f"https://ac.stock.naver.com/ac?q={name}&target=stock"
            try:
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3).json()
                items = res.get("items", [])
                if items and isinstance(items, list) and items[0]:
                    symbol = items[0][0][0] if isinstance(items[0][0], list) else items[0][0].get("code", "")
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

    check_exist = supabase.table("stock_portfolio").select("*").eq("symbol", symbol).execute()
    existing_stock = check_exist.data[0] if check_exist.data else None

    # [신규 매수 또는 추가 매수]
    if action in ["new_buy", "add_buy"]:
        if existing_stock:
            ext_qty = float(existing_stock.get("quantity") or 0)
            ext_price = float(existing_stock.get("avg_price") or 0)
            # 평단가 가중평균 계산
            total_cost = (ext_qty * ext_price) + (quantity * avg_price)
            new_qty = ext_qty + quantity
            new_avg = round(total_cost / new_qty, 2) if new_qty > 0 else avg_price
            supabase.table("stock_portfolio").update({"quantity": new_qty, "avg_price": new_avg, "name": name}).eq("id", existing_stock["id"]).execute()
            message = f"[{name}] 매수 반영 완료. (합산 평단가: ₩{new_avg})"
        else:
            supabase.table("stock_portfolio").insert({"market": market, "symbol": symbol, "name": name, "quantity": quantity, "avg_price": avg_price}).execute()
            message = f"[{name}] 신규 종목 등록 완료."

    # [부분 매도]
    elif action == "sell_part":
        if not existing_stock:
            return jsonify({"status": "error", "message": "보유하지 않은 종목은 매도할 수 없습니다."}), 400
        
        ext_qty = float(existing_stock.get("quantity") or 0)
        ext_price = float(existing_stock.get("avg_price") or 0)
        
        if ext_qty < quantity:
            return jsonify({"status": "error", "message": f"보유량({ext_qty}주)보다 매도량({quantity}주)이 많습니다."}), 400
        
        new_qty = ext_qty - quantity
        
        # 💡 [부분 매도 실현손익 정산] 매도 단가 기준으로 실현손익 누적 계산
        exchange_rate = ExchangeRateService().get_usd_krw()
        if market == "KR":
            profit_krw = int((avg_price - ext_price) * quantity)
        else:
            profit_krw = int((avg_price - ext_price) * quantity * exchange_rate)
            
        # 누적 기록
        cur_realized = supabase.table("realized_profit").select("amount").eq("id", 1).execute()
        old_amt = int(cur_realized.data[0]["amount"]) if cur_realized.data else 0
        supabase.table("realized_profit").update({"amount": old_amt + profit_krw}).eq("id", 1).execute()

        if new_qty <= 0:
            supabase.table("stock_portfolio").delete().eq("id", existing_stock["id"]).execute()
            message = f"[{name}] 전량 매도 정산되어 포트폴리오에서 삭제되었습니다."
        else:
            supabase.table("stock_portfolio").update({"quantity": new_qty}).eq("id", existing_stock["id"]).execute()
            message = f"[{name}] {quantity}주 부분 매도 처리 및 실현손익 반영 완료."

    return jsonify({"status": "success", "message": message})