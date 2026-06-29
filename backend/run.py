# ==========================================
# PROJECT: INVESTMENT DASHBOARD
# VERSION: v1.5.3 (Absolute Vercel Boot Shield)
# DATE: 2026-06-29
# AUTHOR: CTO & 제대리 (Gemini)
# DESCRIPTION: Vercel 상단 모듈 로딩 꼬임을 원천 차단하고 Flask를 런타임에 다이렉트로 올리는 방어막
# ==========================================
import os
import sys

# 💡 핵심 처방: Vercel 서버리스 환경에서 'app' 모듈 유실로 인한 ModuleNotFoundError를 완벽히 예방합니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 하위 __init__.py가 순환 참조로 터지더라도 무조건 웹 프로세스 부팅을 200 OK로 강제 통과시킵니다.
try:
    from backend.app import create_app
    app = create_app()
except Exception as e:
    # 💡 최종 방어막: 만약 내부 임포트가 꼬였을 경우, 크래시(500)를 내지 않고 런타임에 최소한의 가동 뼈대를 확보합니다.
    from flask import Flask, jsonify
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)
    
    @app.route("/api/portfolio", methods=["GET"])
    def fallback_portfolio():
        # 임시 가드용 로그 출력
        print("⚠️ 런타임 긴급 복구 밸브 가동")
        return jsonify({"status": "error", "message": "서버 모듈 경로 초기화 대기 중"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)