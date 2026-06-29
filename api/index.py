import os
import sys

# 💡 Vercel 람다 컨테이너가 backend 폴더 내부를 완벽하게 탐색할 수 있도록 경로 주입 마법을 부립니다.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.run import app