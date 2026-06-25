import os
from dotenv import load_dotenv

# 프로젝트 최상위 루트에 있는 .env 로드
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

class Config:
    """애플리케이션 환경 설정 클래스"""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    
    # DB 주소 설정 (기본값은 sqlite)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///investment.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # API 외부 키
    FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")