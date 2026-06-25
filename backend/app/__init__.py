import os
from flask import Flask
from flask_cors import CORS
from backend.app.config import Config
from backend.app.database import db

def create_app():
    """Flask 애플리케이션 팩토리 함수"""
    # 프론트엔드 폴더 위치 매핑
    app = Flask(__name__, 
                template_folder=os.path.join(os.path.dirname(__file__), '../../frontend/templates'),
                static_folder=os.path.join(os.path.dirname(__file__), '../../frontend/static'))
    
    # 1. 환경 설정 로드
    app.config.from_object(Config)
    
    # 2. CORS 보안 정책 허용 설정
    CORS(app)
    
    # 3. 데이터베이스 초기화 및 앱 바인딩
    db.init_app(app)
    
    # 4. ⚠️ 라우터(연결 통로) 등록 프로세스 가동!
    from backend.app.routes.api import api_blueprint
    app.register_blueprint(api_blueprint)
    
    # 기본 홈 주소 접속 시 대시보드 HTML 파일 렌더링
    from flask import render_template
    @app.route("/")
    def index():
        return render_template("index.html")
        
    return app