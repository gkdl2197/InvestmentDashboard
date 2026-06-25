# backend/run.py
import os
from backend.app import create_app

# Vercel 서버리스 규격에 맞추어 app 인스턴스를 생성합니다.
app = create_app()

# 💡 Vercel 배포 환경에서는 자체 서버를 쓰므로 아래 로컬 구동 코드는 인프라 충돌 방지를 위해 생략합니다.
if __name__ == "__main__":
    app.run(debug=True)