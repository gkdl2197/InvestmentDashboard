import requests

class KrStockService:
    @staticmethod
    def get_realtime_price(symbol: str) -> dict:
        """네이버 모바일 증권 API로 한국 주식 실시간 시세 조회"""
        try:
            url = f"https://m.stock.naver.com/api/stock/{symbol}/basic"
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
                "Referer": "https://m.stock.naver.com/"
            }
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code != 200:
                print(f"⚠️ [KR] {symbol} HTTP {res.status_code}")
                return None

            data = res.json()

            current_price = int(str(data.get("closePrice", "0")).replace(",", ""))
            chg_percent   = float(str(data.get("fluctuationsRatio", "0")).replace("%", "").strip())

            if current_price == 0:
                return None

            return {
                "current_price": current_price,
                "chg_percent": chg_percent
            }

        except Exception as e:
            print(f"⚠️ [KR] {symbol} 조회 실패: {e}")
            return None