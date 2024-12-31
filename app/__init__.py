from flask import Flask
from flask_cors import CORS
from app.chat import chat_blueprint
from app.document_service import document_blueprint
from app.common_utils  import init_logging

def create_app():
    app = Flask(__name__)

    # CORS 설정
    CORS(app, resources={r"/*": {"origins": ["http://localhost:3000"]}},
         supports_credentials=True)

    # 로깅 초기화
    init_logging()

    # 블루프린트 등록
    app.register_blueprint(chat_blueprint, url_prefix="/chat")
    app.register_blueprint(document_blueprint, url_prefix="/document")

    return app
