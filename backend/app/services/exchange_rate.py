import requests
from bs4 import BeautifulSoup

class ExchangeRateService:
    def __init__(self):
        # 💡 OpenAI 관련 코드 및 필수 키 검증 로직을 완전히 삭제하여 클라우드 충돌을 원천 차단합니다.
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }

    def get_usd_krw(self):
        """네이버 금융에서 실시간 고시환율을 안전하게 파싱합니다."""
        try:
            url = "https://finance.naver.com/marketindex/"
            response = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            
            exchange_rate = soup.select_one("#exchangeList > li.on > a.head.usd > div > span.value")
            if exchange_rate:
                return float(exchange_rate.text.replace(",", ""))
            
            # 크롤링 셀렉터 변경 대비 서브 파싱 로직
            alternate = soup.select_one(".value")
            if alternate:
                return float(alternate.text.replace(",", ""))
                
            return 1350.0  # 최종 예외 네트워크 에러 시 기본 방어 환율
        except Exception as e:
            print(f"환율 수집 중 에러 발생: {e}")
            return 1350.0