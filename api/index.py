import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.run import app

# Vercel이 찾는 핸들러
handler = app