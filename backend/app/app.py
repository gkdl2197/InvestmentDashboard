import os
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# ⚠️ 본인의 Finnhub API Key 확인!
FINNHUB_API_KEY = "d8tj97pr01qhcnk3vudgd8tj97pr01qhcnk3vue0"

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), 'data', 'portfolio.json')

def load_portfolio():
    with open(PORTFOLIO_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_us_realtime_price(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if "c" in data and data["c"] != 0:
            return {"current_price": float(data["c"]), "chg_percent": float(data["dp"])}
    except Exception as e:
        print(f"{symbol} 미국 주가 실패: {e}")
    return None

def get_kr_realtime_price(symbol):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
    }
    url = f"https://finance.naver.com/item/main.naver?code={symbol}"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        no_today = soup.find('p', {'class': 'no_today'})
        if not no_today: return None
        blind_val = no_today.find('span', {'class': 'blind'})
        current_price = int(blind_val.text.replace(',', ''))
        
        no_exday = soup.find('p', {'class': 'no_exday'})
        ico = no_exday.find('span', {'class': 'ico'})
        is_down = "하락" in ico.text if ico else False
        blind_chg = no_exday.find_all('span', {'class': 'blind'})
        if len(blind_chg) >= 2:
            chg_percent = float(blind_chg[1].text.replace('%', '').strip())
            if is_down: chg_percent = -chg_percent
        else:
            chg_percent = 0.0
        return {"current_price": current_price, "chg_percent": chg_percent}
    except Exception as e:
        print(f"{symbol} 한국 주가 실패: {e}")
    return None

def get_exchange_rate():
    """네이버 금융에서 원/달러 환율을 실시간으로 가져옵니다."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = "https://finance.naver.com/marketindex/"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        exchange_rate = soup.find('span', {'class': 'value'}).text
        return float(exchange_rate.replace(',', ''))
    except Exception as e:
        print(f"환율 가져오기 실패: {e}")
        return 1350.0  # 실패 시 기본 방어 환율

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/portfolio")
def get_portfolio():
    portfolio = load_portfolio()
    exchange_rate = get_exchange_rate()
    
    total_purchase = 0  # 총 매수 금액 (원화 기준)
    total_evaluation = 0  # 총 평가 금액 (원화 기준)
    total_today_profit = 0  # 오늘 하루 총 손익 (원화 기준)

    # 1. 미국 주식 실시간 계산
    for stock in portfolio.get("US", []):
        realtime_data = get_us_realtime_price(stock["symbol"])
        if realtime_data:
            stock["current_price"] = realtime_data["current_price"]
            stock["chg_percent"] = realtime_data["chg_percent"]
        else:
            stock["current_price"] = stock["avg_price"]
            stock["chg_percent"] = 0.0
        
        # 원화 환산 가치 계산
        purchase_krw = stock["avg_price"] * stock["quantity"] * exchange_rate
        eval_krw = stock["current_price"] * stock["quantity"] * exchange_rate
        
        # Finnhub의 chg_percent와 현재가로 오늘 하루만의 변동금액 유추 계산
        prev_price = stock["current_price"] / (1 + (stock["chg_percent"] / 100))
        today_profit_krw = (stock["current_price"] - prev_price) * stock["quantity"] * exchange_rate
        
        total_purchase += purchase_krw
        total_evaluation += eval_krw
        total_today_profit += today_profit_krw

    # 2. 한국 주식 실시간 계산
    for stock in portfolio.get("KR", []):
        realtime_data = get_kr_realtime_price(stock["symbol"])
        if realtime_data:
            stock["current_price"] = realtime_data["current_price"]
            stock["chg_percent"] = realtime_data["chg_percent"]
        else:
            stock["current_price"] = stock["avg_price"]
            stock["chg_percent"] = 0.0
            
        purchase_krw = stock["avg_price"] * stock["quantity"]
        eval_krw = stock["current_price"] * stock["quantity"]
        
        prev_price = stock["current_price"] / (1 + (stock["chg_percent"] / 100))
        today_profit_krw = (stock["current_price"] - prev_price) * stock["quantity"]
        
        total_purchase += purchase_krw
        total_evaluation += eval_krw
        total_today_profit += today_profit_krw

    # 3. 종합 계좌 데이터 요약
    total_profit = total_evaluation - total_purchase
    total_profit_percent = (total_profit / total_purchase * 100) if total_purchase > 0 else 0.0

    summary = {
        "total_evaluation": int(total_evaluation),
        "total_profit": int(total_profit),
        "total_profit_percent": round(total_profit_percent, 2),
        "total_today_profit": int(total_today_profit),
        "exchange_rate": exchange_rate,
        "portfolio": portfolio
    }

    return jsonify(summary)

if __name__ == "__main__":
    app.run(debug=True)