import requests
from backend.app.config import Config

class UsStockService:
    @staticmethod
    def get_realtime_price(symbol: str) -> dict:
        """Finnhub API를 통해 미국 주식의 실시간 시세를 조회합니다."""
        api_key = Config.FINNHUB_API_KEY
        if not api_key or "발급받은" in api_key:
            print(f"⚠️ [Service] Finnhub API Key가 올바르지 않습니다. ({symbol} 조회 스킵)")
            return None

        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if "c" in data and data["c"] != 0:
                return {
                    "current_price": float(data["c"]),
                    "chg_percent": float(data["dp"])
                }
        except Exception as e:
            print(f"⚠️ [Service] 미국 주가({symbol}) 조회 실패: {e}")
        return None