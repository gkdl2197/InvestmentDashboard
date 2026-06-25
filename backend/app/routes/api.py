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
        return jsonify({"status": "error", "message": "Supabase 설정이 누락되었습니다."}), 500

    # 1. 클라우드 DB에서 전체 주식 목록 읽기
    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
    except Exception as e:
        print(f"❌ [API] Supabase 데이터 로드 실패: {e}")
        return jsonify({"status": "error", "message": f"클라우드 데이터 로드 실패: {e}"}), 500

    exchange_rate = ExchangeRateService.get_rate()
    portfolio = {"US": [], "KR": []}
    total_purchase = 0       
    total_evaluation = 0     
    total_today_profit = 0   

    for stock in db_stocks:
        # 💡 [안전장치] 수량과 평단가가 어떤 형태로 들어와도 안전하게 수치(float)로 변환하도록 방어 코딩
        try:
            qty = float(stock.get("quantity", 0) or 0)
            avg_p = float(stock.get("avg_price", 0) or 0)
        except (ValueError, TypeError):
            qty = 0.0
            avg_p = 0.0

        stock_data = {
            "id": stock.get("id"),
            "symbol": stock.get("symbol", ""),
            "name": stock.get("name") if stock.get("name") else stock.get("symbol", ""),
            "quantity": qty,
            "avg_price": avg_p,
            "current_price": avg_p,  
            "chg_percent": 0.0,
            "purchase_amount_krw": 0,
            "eval_amount_krw": 0,
            "total_profit_krw": 0,
            "total_profit_percent": 0.0,
            "weight_percent": 0.0
        }
        
        market = stock.get("market", "KR")
        if market == "US":
            realtime = UsStockService.get_realtime_price(stock_data["symbol"])
            if realtime:
                stock_data["current_price"] = float(realtime.get("current_price", avg_p))
                stock_data["chg_percent"] = float(realtime.get("chg_percent", 0.0))
            
            stock_data["purchase_amount_krw"] = int(stock_data["avg_price"] * stock_data["quantity"] * exchange_rate)
            stock_data["eval_amount_krw"] = int(stock_data["current_price"] * stock_data["quantity"] * exchange_rate)
            
            prev_price = stock_data["current_price"] / (1 + (stock_data["chg_percent"] / 100)) if stock_data["chg_percent"] != -100 else stock_data["current_price"]
            today_profit_krw = (stock_data["current_price"] - prev_price) * stock_data["quantity"] * exchange_rate
            portfolio["US"].append(stock_data)
            
        elif market == "KR":
            realtime = KrStockService.get_realtime_price(stock_data["symbol"])
            if realtime:
                stock_data["current_price"] = float(realtime.get("current_price", avg_p))
                stock_data["chg_percent"] = float(realtime.get("chg_percent", 0.0))
                
            stock_data["purchase_amount_krw"] = int(stock_data["avg_price"] * stock_data["quantity"])
            stock_data["eval_amount_krw"] = int(stock_data["current_price"] * stock_data["quantity"])
            
            prev_price = stock_data["current_price"] / (1 + (stock_data["chg_percent"] / 100)) if stock_data["chg_percent"] != -100 else stock_data["current_price"]
            today_profit_krw = (stock_data["current_price"] - prev_price) * stock_data["quantity"]
            portfolio["KR"].append(stock_data)

        stock_data["total_profit_krw"] = stock_data["eval_amount_krw"] - stock_data["purchase_amount_krw"]
        if stock_data["purchase_amount_krw"] > 0:
            stock_data["total_profit_percent"] = round((stock_data["total_profit_krw"] / stock_data["purchase_amount_krw"]) * 100, 2)

        total_purchase += stock_data["purchase_amount_krw"]
        total_evaluation += stock_data["eval_amount_krw"]
        total_today_profit += today_profit_krw

    if total_evaluation > 0:
        for stock in portfolio["US"]:
            stock["weight_percent"] = round((stock["eval_amount_krw"] / total_evaluation) * 100, 1)
        for stock in portfolio["KR"]:
            stock["weight_percent"] = round((stock["eval_amount_krw"] / total_evaluation) * 100, 1)

    total_profit = total_evaluation - total_purchase
    total_profit_percent = (total_profit / total_purchase * 100) if total_purchase > 0 else 0.0

    return jsonify({
        "total_evaluation": int(total_evaluation),
        "total_profit": int(total_profit),
        "total_profit_percent": round(total_profit_percent, 2),
        "total_today_profit": int(total_today_profit),
        "exchange_rate": exchange_rate,
        "portfolio": portfolio
    })

@api_blueprint.route("/stock/search", methods=["GET"])
def search_stock():
    market = request.args.get("market")
    query = request.args.get("query", "").strip()
    if not query or len(query) < 2:
        return jsonify([])
    results = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Referer': 'https://finance.naver.com'
    }
    if market == "KR":
        url = f"https://ac.stock.naver.com/ac?q={query}&target=stock,index,fund,futures,option"
        try:
            res = requests.get(url, headers=headers, timeout=5).json()
            items = res.get("items", [])
            for item in items[:8]:
                results.append({"symbol": item.get("code", ""), "name": item.get("name", "")})
        except Exception as e:
            print(f"국내 종목 자동검색 실패: {e}")
    elif market == "US":
        api_key = Config.FINNHUB_API_KEY
        url = f"https://finnhub.io/api/v1/search?q={query}&token={api_key}"
        try:
            res = requests.get(url, timeout=5).json()
            if "result" in res:
                for item in res["result"][:5]:
                    results.append({"symbol": item["symbol"], "name": item["description"]})
        except Exception as e:
            print(f"미국 종목 자동검색 실패: {e}")
    return jsonify(results)

@api_blueprint.route("/portfolio/save", methods=["POST"])
def save_stock():
    data = request.json
    action = data.get("action", "update") 
    stock_id = data.get("id") 
    market = data.get("market")
    symbol = data.get("symbol", "").strip().upper()
    name = data.get("name", "").strip()
    quantity = float(data.get("quantity", 0))
    avg_price = float(data.get("avg_price", 0))

    if action == "delete" and stock_id:
        try:
            supabase.table("stock_portfolio").delete().eq("id", stock_id).execute()
            return jsonify({"status": "success", "message": "종목이 완전히 제거되었습니다."})
        except Exception as e:
            return jsonify({"status": "error", "message": f"삭제 실패: {e}"}), 500

    if not market or not name:
        return jsonify({"status": "error", "message": "구분과 종목명을 정확히 입력해 주세요."}), 400

    if not symbol:
        if market == "KR":
            url = f"https://ac.stock.naver.com/ac?q={name}&target=stock"
            try:
                res = requests.get(url, timeout=3).json()
                if "items" in res and res["items"]:
                    symbol = res["items"][0].get("code", "")
                    name = res["items"][0].get("name", "")
            except Exception: pass
        elif market == "US":
            api_key = Config.FINNHUB_API_KEY
            url = f"https://finnhub.io/api/v1/search?q={name}&token={api_key}"
            try:
                res = requests.get(url, timeout=3).json()
                if "result" in res and res["result"]:
                    symbol = res["result"][0]["symbol"]
                    name = res["result"][0]["description"]
            except Exception: pass

    if not symbol:
        return jsonify({"status": "error", "message": f"'{name}'의 코드를 자동 매핑하지 못했습니다."}), 404

    check_exist = supabase.table("stock_portfolio").select("*").eq("symbol", symbol).execute()
    existing_stock = check_exist.data[0] if check_exist.data else None

    if action == "buy" and existing_stock:
        ext_qty = float(existing_stock["quantity"] or 0)
        ext_price = float(existing_stock["avg_price"] or 0)
        total_cost = (ext_qty * ext_price) + (quantity * avg_price)
        new_qty = ext_qty + quantity
        new_avg = round(total_cost / new_qty, 2)
        
        supabase.table("stock_portfolio").update({"quantity": new_qty, "avg_price": new_avg}).eq("id", existing_stock["id"]).execute()
        message = f"{name} 주식이 {quantity}주 추가 매수되어 평단가가 {new_avg}로 갱신되었습니다."
        
    elif action == "sell" and existing_stock:
        ext_qty = float(existing_stock["quantity"] or 0)
        if ext_qty < quantity:
            return jsonify({"status": "error", "message": f"매도 요청 수량이 보유 수량({ext_qty}주)보다 많습니다."}), 400
        new_qty = ext_qty - quantity
        if new_qty <= 0:
            supabase.table("stock_portfolio").delete().eq("id", existing_stock["id"]).execute()
            message = f"{name} 주식이 전량 매도되어 포트폴리오에서 삭제되었습니다."
        else:
            supabase.table("stock_portfolio").update({"quantity": new_qty}).eq("id", existing_stock["id"]).execute()
            message = f"{name} 주식이 {quantity}주 부분 매도되었습니다. (잔여: {new_qty}주)"
            
    else:
        if quantity <= 0:
            if existing_stock:
                supabase.table("stock_portfolio").delete().eq("id", existing_stock["id"]).execute()
                return jsonify({"status": "success", "message": f"{name} 종목이 제거되었습니다."})
        if existing_stock:
            supabase.table("stock_portfolio").update({"name": name, "quantity": quantity, "avg_price": avg_price}).eq("id", existing_stock["id"]).execute()
            message = f"{name} 정보가 입력값으로 완전히 재설정되었습니다."
        else:
            supabase.table("stock_portfolio").insert({"market": market, "symbol": symbol, "name": name, "quantity": quantity, "avg_price": avg_price}).execute()
            message = f"{name} 종목이 새롭게 등록되었습니다."

    return jsonify({"status": "success", "message": message})

@api_blueprint.route("/ai/report", methods=["GET"])
def get_ai_report():
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return jsonify({"status": "error", "message": ".env 파일에 OPENAI_API_KEY를 등록해 주세요."}), 400

    try:
        res = supabase.table("stock_portfolio").select("*").execute()
        db_stocks = res.data if res.data else []
    except Exception:
        return jsonify({"status": "error", "message": "DB 통신 실패"}), 500

    if not db_stocks:
        return jsonify({"report": "포트폴리오에 자산이 비어있어 AI가 분석할 수 없습니다. 종목을 먼저 추가해 주세요."})

    portfolio_summary = []
    stock_names = []
    for s in db_stocks:
        portfolio_summary.append(f"- {s.get('name')} ({s.get('market')}): 보유량 {s.get('quantity')}주, 평단가 {s.get('avg_price')}")
        stock_names.append(s.get('name'))

    news_context = []
    for name in stock_names[:3]:
        news_context.append(f"[{name} 관련 최신 동향] 시장 내 거래량 변동성 및 투자 심리 변화 관측 중.")

    prompt = f"""
    당신은 월스트리트 출신의 전문 수석 AI 금융 애널리스트입니다. 
    다음은 사용자의 실시간 주식 포트폴리오 자산 보유 현황입니다:
    {chr(10).join(portfolio_summary)}

    참고 동향:
    {chr(10).join(news_context)}

    위 데이터를 기반으로 전문적이고 가독성 높은 한국어 '투자 위험도 분석 리포트'를 작성해 주세요.
    내용에는 다음 항목이 반드시 명확히 포함되어야 합니다:
    1. 계좌의 핵심 리스크 진단 (환율 변동성 및 자산 편중도 분석)
    2. 보유 종목 중 가장 주의 깊게 모니터링해야 할 타겟 종목 및 그 이유
    3. 향후 시장 대응을 위한 현실적인 포트폴리오 헤지(Hedge) 액션 플랜

    친절하면서도 단호한 전문가의 어조로 작성하고, HTML 줄바꿈 태그(<br>)를 적절히 활용하여 응답해 주세요.
    """

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            },
            timeout=15
        ).json()
        
        ai_message = response['choices'][0]['message']['content']
        return jsonify({"status": "success", "report": ai_message})
    except Exception as e:
        return jsonify({"status": "error", "message": f"AI 생성 실패: {e}"}), 500