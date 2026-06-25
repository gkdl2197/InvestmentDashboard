import requests
from bs4 import BeautifulSoup

class ExchangeRateService:
    @staticmethod
    def get_rate() -> float:
        """네이버 금융에서 실시간 원/달러 환율을 수집합니다."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
        }
        url = "https://finance.naver.com/marketindex/"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(response.text, 'html.parser')
            exchange_rate = soup.find('span', {'class': 'value'}).text
            return float(exchange_rate.replace(',', ''))
        except Exception as e:
            print(f"⚠️ [Service] 환율 데이터 수집 실패: {e}")
            return 1350.0  # 시스템 다운을 방지하기 위한 방어용 기본 환율