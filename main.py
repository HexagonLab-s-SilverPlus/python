from flask import Flask
from flask_cors import CORS
import chat
import document_service
import stt
import tts
import emg

app = Flask(__name__)

# CORS 설정
CORS(app,
     resources={r"/*": {"origins": "http://localhost:3000"}},
     supports_credentials=True)

# /chat 및 /document 경로 등록
chat.register_routes(app)
document_service.register_routes(app)
stt.register_routes(app)
tts.register_routes(app)
emg.register_routes(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
