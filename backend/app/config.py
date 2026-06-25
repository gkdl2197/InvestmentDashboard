import os
from dotenv import load_dotenv

# 프로젝트 최상위 루트에 있는 .env 로드
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

class Config:
    """애플리케이션 환경 설정 클래스"""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    
    # 💡 [Vercel Read-only 방어 스위치]
    if os.getenv("VERCEL") == "1":
        # 클라우드 환경일 때는 파일 생성을 방지하기 위해 메모리 DB 기본값을 줍니다.
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    else:
        # 내 컴퓨터(로컬)일 때는 기존 코드 그대로 작동합니다.
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///investment.db")
        
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # API 외부 키
    FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")