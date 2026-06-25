# api/index.py
import sys
import os

# 💡 Vercel 클라우드 환경에서 최상위 및 backend/frontend 폴더를 완벽하게 탐색하도록 인프라 경로 주입
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# 기존 Flask 앱 인스턴스를 다이렉트로 로드합니다.
from backend.run import app