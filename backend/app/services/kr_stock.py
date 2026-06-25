import requests
from bs4 import BeautifulSoup

class KrStockService:
    @staticmethod
    def get_realtime_price(symbol: str) -> dict:
        """네이버 금융 스크래핑을 통해 한국 주식의 실시간 시세를 조회합니다."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
        }
        url = f"https://finance.naver.com/item/main.naver?code={symbol}"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 현재가 파싱
            no_today = soup.find('p', {'class': 'no_today'})
            if not no_today: return None
            blind_val = no_today.find('span', {'class': 'blind'})
            current_price = int(blind_val.text.replace(',', ''))
            
            # 등락률 파싱
            no_exday = soup.find('p', {'class': 'no_exday'})
            ico = no_exday.find('span', {'class': 'ico'})
            is_down = "하락" in ico.text if ico else False
            
            blind_chg = no_exday.find_all('span', {'class': 'blind'})
            if len(blind_chg) >= 2:
                chg_percent = float(blind_chg[1].text.replace('%', '').strip())
                if is_down:
                    chg_percent = -chg_percent
            else:
                chg_percent = 0.0
                
            return {
                "current_price": current_price,
                "chg_percent": chg_percent
            }
        except Exception as e:
            print(f"⚠️ [Service] 한국 주가({symbol}) 조회 실패: {e}")
        return None