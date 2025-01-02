import os
from flask import Blueprint, request, jsonify
from flask_cors import CORS
from .common_utils import token_required, log, g
import requests
import speech_recognition as sr

stt_blueprint = Blueprint("stt", __name__)

# Flask 초기 설정
CORS(stt_blueprint, resources={r"/*": {"origins": ["http://localhost:3000", "http://localhost"]}})

# 환경 변수 로드
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")

@stt_blueprint.route("/process-audio", methods=["POST"])
@token_required
def process_audio(current_user):
    """
    음성 데이터를 Google STT를 사용해 텍스트로 변환하고 Spring Boot로 전달.
    """
    token = g.get("access_token", None)
    refresh_token_header = request.headers.get('RefreshToken', '')
    refresh_token = refresh_token_header.split(' ')[1] if 'Bearer ' in refresh_token_header else None

    if not token or not refresh_token:
        return jsonify({"error": "Missing accessToken or refreshToken."}), 401

    # 음성 파일 처리
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided."}), 400

    audio_file = request.files['audio']
    recognizer = sr.Recognizer()
    try:
        # WAV 파일을 바로 Google STT로 처리
        with sr.AudioFile(audio_file) as source:
            audio_data = recognizer.record(source)
            recognized_text = recognizer.recognize_google(audio_data, language='ko-KR')
            log.info(f"Recognized text: {recognized_text}")
    except sr.UnknownValueError:
        log.warning("STT could not understand audio.")
        return jsonify({"error": "Audio could not be understood"}), 400
    except sr.RequestError as e:
        log.error(f"STT request failed: {e}")
        return jsonify({"error": "STT service unavailable"}), 503
    except Exception as e:
        log.error(f"Unexpected error during STT processing: {e}")
        return jsonify({"error": "Unexpected error"}), 500

    # Spring Boot로 텍스트 전달
    headers = {
        'Authorization': f'Bearer {token}',
        'RefreshToken': f'Bearer {refresh_token}'
    }
    text_data = {
        "userId": current_user,
        "recognizedText": recognized_text
    }

    try:
        response = requests.post(f"{SPRING_BOOT_API_URL}/api/audio/processed-text", json=text_data, headers=headers)
        if response.status_code == 200:
            return jsonify({"recognized_text": recognized_text}), 200
        else:
            log.error(f"Text data delivery failed: {response.text}")
            return jsonify({"error": "Failed to deliver text data to Spring Boot"}), 500
    except Exception as e:
        log.error(f"Text data delivery error: {e}")
        return jsonify({"error": f"Unexpected error while delivering data: {e}"}), 500
