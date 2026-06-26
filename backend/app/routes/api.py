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

# ==========================================
# PROJECT: INVESTMENT DASHBOARD
# VERSION: v1.1.0 (Dual-Track Transaction Engine)
# DATE: 2026-06-26
# AUTHOR: 제대리 (Gemini)
# DESCRIPTION: 매수/매도 분리, 이동평균 평단가 계산, 수량 0일 때 자동 삭제 로직 구현
# ==========================================

@api_blueprint.route("/portfolio", methods=["GET"])
def get_portfolio():
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500

    db_stocks = []
    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
    except Exception as e:
        return jsonify({"status": "error", "message": f"DB 로드 에러: {str(e)}"}), 500

    exchange_rate = ExchangeRateService().get_usd_krw() or 1350.0
    portfolio = {"KR": [], "US": []}
    
    total_eval_krw = 0
    total_pur_krw = 0  # KRW 총 매수금액 (수익률 계산용)
    
    total_eval_usd = 0
    total_pur_usd = 0  # USD 총 매수금액 (수익률 계산용)

    for stock in db_stocks:
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
            market = stock.get("market", "KR")
            symbol = stock.get("symbol", "")
            
            if qty <= 0: continue # 0 이하 가드라인

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

    # 💡 상단 카드 표시용 수익률 산출
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
def save_portfolio():
    if not supabase: return jsonify({"status": "error", "message": "Supabase 미연결"}), 500
    
    data = request.get_json()
    market = data.get("market", "KR")
    symbol = data.get("symbol")
    name = data.get("name")
    tx_type = data.get("tx_type", "BUY") # 💡 BUY 또는 SELL 판별
    input_qty = float(data.get("quantity", 0))
    input_price = float(data.get("avg_price", 0))
    
    if not symbol:
        return jsonify({"status": "error", "message": "종목 코드가 누락되었습니다."}), 400

    try:
        # 기존 보유 내역이 있는지 조회
        existing = supabase.table("stock_portfolio").select("*").eq("symbol", symbol).execute()
        
        if existing.data and len(existing.data) > 0:
            current_stock = existing.data[0]
            old_qty = float(current_stock.get("quantity", 0) or 0)
            old_price = float(current_stock.get("avg_price", 0) or 0)
            
            if tx_type == "BUY":
                # 💡 [추가 매수] 이동평균법 적용: (기존총액 + 신규총액) / 전체수량
                new_qty = old_qty + input_qty
                new_price = ((old_price * old_qty) + (input_price * input_qty)) / new_qty if new_qty > 0 else 0
                
                supabase.table("stock_portfolio").update({
                    "quantity": new_qty, "avg_price": round(new_price, 2) if market=="US" else int(new_price)
                }).eq("symbol", symbol).execute()
                
            else:
                # 💡 [분할 매도] 평단가는 유지하되 수량만 차감
                new_qty = old_qty - input_qty
                
                if new_qty <= 0:
                    # 💡 보유 수량이 0 이하가 되면 DB에서 깔끔하게 삭제
                    supabase.table("stock_portfolio").delete().eq("symbol", symbol).execute()
                else:
                    supabase.table("stock_portfolio").update({
                        "quantity": new_qty
                    }).eq("symbol", symbol).execute()
        else:
            # 신규 진입인데 매도를 먼저 누른 가드라인 예외처리
            if tx_type == "SELL":
                return jsonify({"status": "error", "message": "보유하지 않은 종목은 매도할 수 없습니다."}), 400
                
            # 최초 매수 등록
            supabase.table("stock_portfolio").insert({
                "market": market, "symbol": symbol, "name": name,
                "quantity": input_qty, "avg_price": input_price
            }).execute()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500