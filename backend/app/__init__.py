import os
from flask import Flask, render_template
from flask_cors import CORS
from backend.app.config import Config
from backend.app.database import db

def create_app():
    app = Flask(__name__, 
                template_folder=os.path.join(os.path.dirname(__file__), '../../frontend/templates'),
                static_folder=os.path.join(os.path.dirname(__file__), '../../frontend/static'))
    
    app.config.from_object(Config)
    CORS(app)
    db.init_app(app)
    
    from backend.app.routes.api import api_blueprint
    app.register_blueprint(api_blueprint, url_prefix='/api')
    
    @app.route("/")
    def index():
        return render_template("index.html")
        
    return app