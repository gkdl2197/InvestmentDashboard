# ==========================================
# PROJECT: INVESTMENT DASHBOARD
# VERSION: v1.3.4 (Ultimate Unified Engine)
# DATE: 2026-06-26
# AUTHOR: 제대리 (Gemini) & CTO
# DESCRIPTION: 국장 스마트 정렬 + 미주 오리지널 Finnhub + 매수/매도/자동삭제 전 로직 무생략 통합본
# ==========================================
import os
import requests
from flask import Blueprint, request, jsonify
from app import supabase
from app.services.stock_service import KrStockService, UsStockService
from app.services.exchange_service import ExchangeRateService

api_blueprint = Blueprint("api", __name__)

@api_blueprint.route("/stock/search", methods=["GET"])
def search_stock():
    if not supabase:
        return jsonify([])

    market = request.args.get("market", "KR")
    query = request.args.get("query", "").strip()

    if not query:
        return jsonify([])

    try:
        # 🇺🇸 1. 미국 주식: 기존에 콸콸 잘 나오던 오리지널 Finnhub API 직결 엔진
        if market == "US":
            FINNHUB_KEY = os.getenv("FINNHUB_API_KEY") or os.getenv("FINNHUB_KEY")
            url = f"https://finnhub.io/api/v1/search?q={query}&token={FINNHUB_KEY}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("result", [])
                
                final_us_items = []
                for item in results[:10]:
                    final_us_items.append({
                        "symbol": item.get("symbol", ""),
                        "name": item.get("description", "")
                    })
                return jsonify(final_us_items)
            return jsonify([])
            
        # 🇰🇷 2. 한국 주식: 우리가 완성한 2,875개 내장 DB 우선순위 가중치 정렬 엔진
        else:
            res = supabase.table("kr_stock_list")\
                .select("symbol,name")\
                .ilike("name", f"%{query}%")\
                .limit(50)\
                .execute()
            
            raw_items = res.data if res.data else []
            
            scored_items = []
            for item in raw_items:
                name = item["name"]
                symbol = item["symbol"]
                score = 0
                
                if name.startswith(query):
                    score += 100
                elif query in name:
                    score += 50
                    
                score -= len(name) * 0.1
                scored_items.append({"symbol": symbol, "name": name, "score": score})
            
            scored_items.sort(key=lambda x: x["score"], reverse=True)
            return jsonify([{"symbol": item["symbol"], "name": item["name"]} for item in scored_items[:10]])

    except Exception as e:
        print(f"❌ 검색 엔진 구동 실패 에러: {str(e)}")
        return jsonify([])


@api_blueprint.route("/portfolio", methods=["GET"])
def get_portfolio():
    if not supabase: 
        return jsonify({"status": "error", "message": "Supabase 미연결"}), 500

    db_stocks = []
    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
    except Exception as e:
        return jsonify({"status": "error", "message": f"DB 로드 에러: {str(e)}"}), 500

    exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
    portfolio = {"KR": [], "US": []}
    
    total_eval_krw = 0
    total_pur_krw = 0
    total_eval_usd = 0
    total_pur_usd = 0

    for stock in db_stocks:
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
            market = stock.get("market", "KR")
            symbol = stock.get("symbol", "")
            
            if qty <= 0: 
                continue

            stock_data = {
                "id": stock.get("id"), "symbol": symbol, "name": stock.get("name") or symbol,
                "quantity": qty, "avg_price": avg_p, "current_price": avg_p, "chg_percent": 0.0,
                "purchase_amount": 0, "eval_amount": 0, "total_profit": 0,
                "total_profit_percent": 0.0, "weight_percent": 0.0, "market": market
            }
            
            if market == "US":
                rt = UsStockService.get_realtime_price(symbol)
                stock_data["purchase_amount"] = round(avg_p * qty, 2)
                if rt:
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                stock_data["eval_amount"] = round(stock_data["current_price"] * qty, 2)
                stock_data["total_profit"] = round(stock_data["eval_amount"] - stock_data["purchase_amount"], 2)
                
                if stock_data["purchase_amount"] > 0:
                    stock_data["total_profit_percent"] = round((stock_data["total_profit"] / stock_data["purchase_amount"]) * 100, 2)
                
                total_pur_usd += stock_data["purchase_amount"]
                total_eval_usd += stock_data["eval_amount"]
            else:
                rt = KrStockService.get_realtime_price(symbol)
                stock_data["purchase_amount"] = int(avg_p * qty)
                if rt:
                    stock_data["current_price"] = float(rt.get("current_price", avg_p))
                stock_data["eval_amount"] = int(stock_data["current_price"] * qty)
                stock_data["total_profit"] = stock_data["eval_amount"] - stock_data["purchase_amount"]
                
                if stock_data["purchase_amount"] > 0:
                    stock_data["total_profit_percent"] = round((stock_data["total_profit"] / stock_data["purchase_amount"]) * 100, 2)
                
                total_pur_krw += stock_data["purchase_amount"]
                total_eval_krw += stock_data["eval_amount"]

            portfolio[market].append(stock_data)
        except Exception:
            continue

    combined_total_krw = total_eval_krw + int(total_eval_usd * exchange_rate)

    if combined_total_krw > 0:
        for m in ["KR", "US"]:
            for s in portfolio[m]:
                eval_krw = (s["eval_amount"] * exchange_rate) if m == "US" else s["eval_amount"]
                s["weight_percent"] = round((eval_krw / combined_total_krw) * 100, 1)

    profit_rate_krw = round(((total_eval_krw - total_pur_krw) / total_pur_krw * 100), 2) if total_pur_krw > 0 else 0.0
    profit_rate_usd = round(((total_eval_usd - total_pur_usd) / total_pur_usd * 100), 2) if total_pur_usd > 0 else 0.0

    return jsonify({
        "total_evaluation_krw": int(total_eval_krw),
        "profit_rate_krw": profit_rate_krw,
        "total_evaluation_usd": round(total_eval_usd, 2),
        "profit_rate_usd": profit_rate_usd,
        "combined_total_krw": combined_total_krw,
        "exchange_rate": exchange_rate, 
        "portfolio": portfolio
    })


@api_blueprint.route("/portfolio/save", methods=["POST"])
def save_portfolio():
    if not supabase: 
        return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    
    data = request.get_json()
    market = data.get("market", "KR")
    symbol = data.get("symbol")
    name = data.get("name")
    tx_type = data.get("tx_type", "BUY")
    input_qty = float(data.get("quantity", 0))
    input_price = float(data.get("avg_price", 0))
    
    if not symbol:
        return jsonify({"status": "error", "message": "종목 코드가 누락되었습니다."}), 400

    try:
        existing = supabase.table("stock_portfolio").select("*").eq("symbol", symbol).execute()
        
        if existing.data and len(existing.data) > 0:
            current_stock = existing.data[0]
            old_qty = float(current_stock.get("quantity", 0) or 0)
            old_price = float(current_stock.get("avg_price", 0) or 0)
            
            if tx_type == "BUY":
                new_qty = old_qty + input_qty
                new_price = ((old_price * old_qty) + (input_price * input_qty)) / new_qty if new_qty > 0 else 0
                
                supabase.table("stock_portfolio").update({
                    "quantity": new_qty, "avg_price": round(new_price, 2) if market=="US" else int(new_price)
                }).eq("symbol", symbol).execute()
                
            else:
                new_qty = old_qty - input_qty
                
                if new_qty <= 0:
                    supabase.table("stock_portfolio").delete().eq("symbol", symbol).execute()
                else:
                    supabase.table("stock_portfolio").update({
                        "quantity": new_qty
                    }).eq("symbol", symbol).execute()
        else:
            if tx_type == "SELL":
                return jsonify({"status": "error", "message": "보유하지 않은 종목은 매도할 수 없습니다."}), 400
                
            supabase.table("stock_portfolio").insert({
                "market": market, "symbol": symbol, "name": name,
                "quantity": input_qty, "avg_price": input_price
            }).execute()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500