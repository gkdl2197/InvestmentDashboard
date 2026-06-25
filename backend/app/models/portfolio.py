from backend.app.database import db

class StockPortfolio(db.Model):
    """보유 주식 자산을 관리하는 데이터베이스 테이블 모델"""
    __tablename__ = 'stock_portfolio'

    # 1. 고유 식별 번호 (기본키)
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # 2. 시장 구분 (예: 'US' 또는 'KR')
    market = db.Column(db.String(10), nullable=False)
    
    # 3. 종목 코드 (예: 'NVDA', '005930')
    symbol = db.Column(db.String(20), nullable=False, unique=True)
    
    # 4. 종목명 (국내 주식 한글 표기용, 미국 주식은 생략 가능)
    name = db.Column(db.String(100), nullable=True)
    
    # 5. 보유 수량 (소수점 자산 지원을 위해 Float 사용)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    
    # 6. 평균 매수 단가
    avg_price = db.Column(db.Float, nullable=False, default=0.0)

    def __repr__(self):
        return f"<Stock {self.market} - {self.symbol} ({self.quantity}주)>"