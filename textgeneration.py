import base64

import openai
import os
from dotenv import load_dotenv
from pathlib import Path
from flask_cors import CORS
import jwt
from functools import wraps
import requests
import uuid
from datetime import datetime, timezone
import logging
from flask import Flask, request, jsonify, send_file
import speech_recognition as sr
from gtts import gTTS
import playsound

# Flask 서버 설정
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000"]}}, allow_headers=["Authorization", "Content-Type"])

# 로깅 설정
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# .env 파일에서 환경 변수 로드
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
SECRET_KEY_BASE64 = os.getenv("JWT_SECRET_KEY")
SECRET_KEY = base64.b64decode(SECRET_KEY_BASE64)
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")


def decode_jwt(token):
    try:
        decoded_token = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"]
        )
        log.debug(f"Decoded token: {decoded_token}")
        return decoded_token
    except jwt.ExpiredSignatureError:
        log.error("Token has expired")
        return None
    except jwt.InvalidTokenError:
        log.error("Invalid token")
        return None


# JWT 토큰 검증 데코레이터
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            log.debug(f"Received token: {token}")
            data = decode_jwt(token)
            log.debug(f"Decoded token: {data}")
            if not data:
                raise Exception("Invalid or expired token")

            member = data.get("member")
            if not member or "memUUID" not in member:
                log.error(f"Decoded token missing 'member' field: {data}")
                raise Exception("Invalid token: Missing member information")

            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token decoding error: {str(e)}")
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user, *args, **kwargs)

    return decorated


# 워크스페이스 자동 생성 로직
def get_or_create_workspace(current_user, token):
    headers = {'Authorization': f'Bearer {token}'}
    workspace_check_url = f"{SPRING_BOOT_API_URL}/api/workspace/{current_user}"

    # 워크스페이스 존재 여부 확인
    workspace_response = requests.get(workspace_check_url, headers=headers)
    log.debug(f"Workspace check response: {workspace_response.status_code}, {workspace_response.text}")

    if workspace_response.status_code == 200:
        try:
            workspace_data = workspace_response.json()
            workspace_id = workspace_data.get("data", {}).get("workspaceId")
            log.info(f"Existing Workspace ID: {workspace_id}")
            return workspace_id
        except Exception as e:
            log.error(f"Failed to parse workspace data: {e}")
            raise Exception("Failed to parse workspace response")

    elif workspace_response.status_code == 404:
        # 워크스페이스 생성 요청
        log.debug(f"Extracted current_user from JWT: {current_user}")
        workspace_create_url = f"{SPRING_BOOT_API_URL}/api/workspace/create?memUuid={current_user}"
        create_response = requests.post(workspace_create_url, headers=headers)
        log.debug(f"Workspace create response: {create_response.status_code}, {create_response.text}")

        if create_response.status_code == 201:
            try:
                created_workspace_data = create_response.json()
                workspace_id = created_workspace_data.get("data", {}).get("workspaceId")
                log.info(f"Created Workspace ID: {workspace_id}")
                return workspace_id
            except Exception as e:
                log.error(f"Failed to parse created workspace data: {e}")
                raise Exception("Failed to parse created workspace response")
        else:
            log.error(f"Workspace creation failed: {create_response.text}")
            raise Exception("Failed to create workspace")
    else:
        log.error(f"Unexpected workspace response: {workspace_response.status_code}")
        raise Exception("Failed to retrieve workspace")


# Chat Completion 엔드포인트
@app.route("/chat", methods=["POST"])
@token_required
def chat(current_user):
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.split(' ')[1] if 'Bearer ' in auth_header else None

    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "No message provided."}), 400

    try:
        # 워크스페이스 조회 또는 생성
        workspace_id = get_or_create_workspace(current_user, token)
    except Exception as e:
        log.error(f"Workspace creation error: {str(e)}")
        return jsonify({"error": "Failed to create or retrieve workspace."}), 500

    user_msg_id = str(uuid.uuid4())

    # ISO 8601 형식 변환
    sent_at = datetime.now(timezone.utc).isoformat()

    # Epoch milliseconds 변환
    sent_at_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)

    log.info(f"보내는 사람 UUID: {current_user}")
    user_chat_data = {
        "msgId": user_msg_id,
        "msgSenderRole": "USER",
        "msgContent": user_message,
        "msgSentAt": sent_at_epoch,  # 변경
        "msgSenderUUID": current_user,
        "parentMsgId": None,
        "msgType": "T",
        "msgWorkspaceId": workspace_id
    }

    headers = {'Authorization': f'Bearer {token}'}
    try:
        response_user = requests.post(
            f"{SPRING_BOOT_API_URL}/api/chat/save",
            json=user_chat_data,
            headers=headers
        )
        log.info(f"Request Payload: {user_chat_data}")
        log.info(f"Response Status Code: {response_user.status_code}")
        log.info(f"Response Body: {response_user.text}")

        if response_user.status_code != 201:
            log.error(f"Failed to save user message: {response_user.text}")
            return jsonify({"error": "Failed to save user message."}), 500
    except Exception as e:
        log.error(f"Exception when saving user message: {str(e)}")
        return jsonify({"error": f"Exception when saving user message: {str(e)}"}), 500

    # OpenAI 호출
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system",
                 "content": "You are a friendly AI assistant designed for elderly users. Speak slowly and respond with warmth."},
                {"role": "user", "content": user_message}
            ]
        )
        ai_reply = response.choices[0].message["content"].strip()
    except Exception as e:
        log.error(f"Exception when calling OpenAI: {str(e)}")
        return jsonify({"error": f"Exception when calling OpenAI: {str(e)}"}), 500

    assistant_msg_id = str(uuid.uuid4())

    # ISO 8601 형식 변환
    sent_at = datetime.now(timezone.utc).isoformat()
    # Epoch milliseconds 변환
    sent_at_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)

    assistant_chat_data = {
        "msgId": assistant_msg_id,
        "msgSenderRole": "AI",
        "msgContent": ai_reply,
        "msgSentAt": sent_at_epoch,  # 변경
        "msgSenderUUID": "ai-uuid-1234-5678-90ab-cdef12345678",
        "parentMsgId": user_msg_id,
        "msgType": "T",
        "msgWorkspaceId": workspace_id
    }

    # AI 메시지 저장
    try:
        response_assistant = requests.post(
            f"{SPRING_BOOT_API_URL}/api/chat/save",
            json=assistant_chat_data,
            headers=headers,
        )
        if response_assistant.status_code != 201:
            log.error(f"Failed to save AI message: {response_assistant.text}")
            return jsonify({"error": "Failed to save AI message."}), 500
    except Exception as e:
        log.error(f"Exception when saving assistant message: {str(e)}")
        return jsonify({"error": f"Exception when saving assistant message: {str(e)}"}), 500

    return jsonify({"reply": ai_reply, "workspaceId": workspace_id})


# TTS 음성 변환 엔드포인트
@app.route("/speak", methods=["POST"])
def speak():
    text = request.json.get("text")
    tts = gTTS(text=text, lang="ko", slow=True)
    speech_file_path = Path("speech.mp3")
    tts.save(speech_file_path)
    return send_file(speech_file_path, mimetype="audio/mpeg")


# STT 음성 인식 엔드포인트
@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        audio_file = request.files["file"]
        audio_path = Path("uploaded_audio.mp3")
        audio_file.save(audio_path)

        with open(audio_path, "rb") as f:
            transcription = openai.Audio.transcriptions.create(
                model="whisper-1",
                file=f
            )

        return jsonify({"transcription": transcription["text"]})
    except Exception as e:
        return jsonify({"error": "Failed to transcribe audio. Please try again."}), 400


# 음성 인식 함수
def listen_for_command_from_file(audio_file):
    recognizer = sr.Recognizer()

    # 음성 파일을 처리
    with sr.AudioFile(audio_file) as source:
        audio = recognizer.record(source)

    try:
        # 구글 음성 인식 API로 텍스트로 변환
        command = recognizer.recognize_google(audio, language="ko-KR")
        print(f"사용자 명령: {command}")
        return command
    except sr.UnknownValueError:
        print("음성을 이해하지 못했습니다.")
        return None
    except sr.RequestError as e:
        print(f"음성 인식 API 에러: {e}")
        return None


# 음성 안내 함수
def speak(text):
    tts = gTTS(text=text, lang="ko")
    tts.save("response.mp3")
    playsound.playsound("response.mp3")


# 페이지로 이동하는 함수
def navigate_page(command):
    if "공지사항" in command:
        speak("공지사항 페이지로 이동합니다")
        return "/notices"  # 공지사항 페이지로 이동
    elif "홈" in command:
        speak("홈 페이지로 이동합니다")
        return "/"  # 홈 페이지로 이동
    elif "말동무" in command:
        speak("말동무 페이지로 이동합니다")
        return "/companion"  # 말동무 페이지로 이동
    else:
        speak("다시 한번 이동하고 싶은 페이지를 말씀해주세요.")
        return None


# 엔드포인트에서 음성 파일을 받아 명령 처리
@app.route('/page-stt', methods=['POST'])
def page_stt():
    if 'file' not in request.files:
        return jsonify({'error': 'No Audio file provided'}), 400

    audio_file = request.files['file']
    audio_path = os.path.join("temp", audio_file.filename)
    audio_file.save(audio_path)

    # 음성 파일을 인식하여 명령 추출
    command = listen_for_command_from_file(audio_path)

    # 명령 처리
    if command:
        page_url = navigate_page(command)  # 명령에 따라 페이지 이동
        if page_url:
            return jsonify({"redirect": page_url}), 200
        else:
            return jsonify({"message": "다시 한번 이동하고 싶은 페이지를 말씀해주세요."}), 400
    else:
        speak("다시 한번 이동하고 싶은 페이지를 말씀해주세요.")
        return jsonify({"message": "명령을 인식할 수 없습니다."}), 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)
