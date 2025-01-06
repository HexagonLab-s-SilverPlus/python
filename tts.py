import tempfile
from flask import Flask, request, Blueprint, send_file
from flask_cors import CORS
from gtts import gTTS
import os
import threading

# Blueprint 생성
tts_blueprint = Blueprint('tts', __name__)
CORS(tts_blueprint, resources={r"/*": {"origins": ["http://localhost:3000", "http://localhost"]}})

# 일정시간 후에 파일 삭제
def delete_file_later(file_path, delay=10):
    def delete_file():
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[DEBUG] 임시파일 삭제 완료 : {file_path}")
        except Exception as e:
            print(f"[ERROR] 파일 삭제 실패 : {str(e)}")

    # delay 초 후에 삭제 작업 실행
    timer = threading.Timer(delay, delete_file)
    timer.start()

@tts_blueprint.route("/pagereader", methods=["POST"])
def text_to_speech():
    try:
        # 클라이언트에서 전송된 텍스트 가져오기
        text = request.json.get("text", "")
        if not text:
            return {"error": "텍스트가 비어 있습니다."}, 400

        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio_file:
            temp_file_path = temp_audio_file.name
            print(f"[DEBUG] 임시 파일 생성: {temp_file_path}")

            # gTTS로 음성 파일 생성
            tts = gTTS(text=text, lang='ko')
            tts.save(temp_file_path)

        # 일정 시간 후 파일 삭제 예약
        delete_file_later(temp_file_path, delay=10)

        return send_file(temp_file_path, mimetype='audio/mpeg')
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        return {"error": "TTS 처리 중 오류 발생", "details": str(e)}, 500
    finally:
        # 요청 완료 후 파일 삭제
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                print(f"[DEBUG] 임시 파일 삭제 완료: {temp_file_path}")
        except Exception as e:
            print(f"[ERROR] 파일 삭제 실패: {str(e)}")

# Blueprint 등록 함수 추가
def register_routes(app):
    '''
    Flask 앱에 TTS 관련 경로를 등록하는 함수
    '''
    app.register_blueprint(tts_blueprint, url_prefix='/tts')
