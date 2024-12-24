import base64
import openai
import os
from dotenv import load_dotenv
from flask_cors import CORS
import jwt
from functools import wraps
import requests
import uuid
from datetime import datetime, timezone
import logging
from flask import Flask, request, jsonify

# Flask 초기 설정
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000"]}}, allow_headers=["Authorization", "Content-Type"])

# 로깅 설정
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
SECRET_KEY_BASE64 = os.getenv("JWT_SECRET_KEY")
SECRET_KEY = base64.b64decode(SECRET_KEY_BASE64)
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")


# JWT 디코딩 함수
def decode_jwt(token):
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded_token
    except jwt.ExpiredSignatureError:
        log.error("JWT has expired")
        return None
    except jwt.InvalidTokenError:
        log.error("Invalid JWT")
        return None


# JWT 인증 데코레이터
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
            data = decode_jwt(token)
            if not data:
                raise Exception("Invalid or expired token")
            member = data.get("member")
            if not member or "memUUID" not in member:
                raise Exception("Invalid token: Missing member information")
            current_user = member["memUUID"]
        except Exception as e:
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user, *args, **kwargs)

    return decorated


def get_workspace(current_user, token):
    refresh_token = request.headers.get("RefreshToken") # refresh token 가져오기
    headers = {
        'Authorization': f'Bearer {token.strip()}',
        'RefreshToken': refresh_token,  # RefreshToken 추가
        'Content-Type': 'application/json'
    }
    workspace_check_url = f"{SPRING_BOOT_API_URL}/api/workspace/{current_user}"
    log.info(f"Requesting workspace with headers: {headers}")
    log.info(f"Workspace check URL: {workspace_check_url}")
    try:
        response = requests.get(workspace_check_url, headers=headers)
        log.info(f"Spring Boot response status: {response.status_code}")
        log.info(f"Spring Boot response body: {response.text}")
        if response.status_code == 200:
            workspace_data = response.json()
            return workspace_data.get("data", {}).get("workspaceId")
        elif response.status_code == 401:
            log.error(": Invalid token")
            raise Exception("Invalid token")
        elif response.status_code == 404:
            return None
        else:
            log.error(f"Spring Boot API 호출 중 오류: {response.text}")
            raise Exception(f"Unexpected error during workspace retrieval: {response.text}")
    except requests.RequestException as e:
        log.error(f"워크스페이스 조회 실패: {e}")
        raise Exception("Workspace retrieval error.")


def create_workspace_if_not_exists(current_user, user_message, ai_reply, token):
    try:
        # 워크스페이스 이름 생성
        summary_response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system",
                 "content": "Summarize the following user and AI response into a concise workspace name."},
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": ai_reply},
            ]
        )
        workspace_name = summary_response.choices[0].message["content"].strip()
    except Exception as e:
        log.error(f"워크스페이스 이름 생성 실패: {e}")
        raise Exception("Workspace name generation failed.")

    # Spring Boot로 워크스페이스 저장
    headers = {'Authorization': f'Bearer {token}'}
    workspace_data = {"memUuid": current_user, "workspaceName": workspace_name}
    try:
        response = requests.post(f"{SPRING_BOOT_API_URL}/api/workspace/create", json=workspace_data, headers=headers)
        if response.status_code == 201:
            workspace_id = response.json().get("data", {}).get("workspaceId")
            return workspace_id
        else:
            log.error(f"Workspace creation failed: {response.text}")
            raise Exception("Workspace creation failed.")
    except Exception as e:
        log.error(f"워크스페이스 저장 중 오류: {e}")
        raise Exception("Workspace creation error.")


# Chat 엔드포인트
@app.route("/chat", methods=["POST"])
@token_required
def chat(current_user):
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.split(' ')[1] if 'Bearer ' in auth_header else None

    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "No message provided."}), 400

    # 워크스페이스 조회 또는 생성
    try:
        workspace_id = get_workspace(current_user, token)
        if not workspace_id:
            ai_reply = "처음 메시지입니다. AI 응답이 준비되었습니다."
            workspace_id = create_workspace_if_not_exists(current_user, user_message, ai_reply, token)
    except Exception as e:
        log.error(f"Workspace error: {e}")
        return jsonify({"error": "Workspace creation or retrieval failed"}), 500

    # 사용자 메시지 저장
    user_msg_id = str(uuid.uuid4())
    sent_at_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)
    user_chat_data = {
        "msgId": user_msg_id,
        "msgSenderRole": "USER",
        "msgContent": user_message,
        "msgSentAt": sent_at_epoch,
        "msgSenderUUID": current_user,
        "parentMsgId": None,
        "msgType": "T",
        "msgWorkspaceId": workspace_id
    }

    headers = {'Authorization': f'Bearer {token}'}
    try:
        response_user = requests.post(f"{SPRING_BOOT_API_URL}/api/chat/save", json=user_chat_data, headers=headers)
        if response_user.status_code != 201:
            log.error(f"사용자 메시지 저장 실패: {response_user.text}")
            return jsonify({"error": "사용자 메시지 저장 실패"}), 500
    except Exception as e:
        log.error(f"사용자 메시지 저장 중 오류: {e}")
        return jsonify({"error": f"사용자 메시지 저장 중 오류: {e}"}), 500

    # AI 응답 생성
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are a friendly AI assistant."},
                {"role": "user", "content": user_message}
            ]
        )
        ai_reply = response.choices[0].message["content"].strip()
    except Exception as e:
        log.error(f"AI 응답 생성 실패: {e}")
        return jsonify({"error": "AI 응답 생성 중 오류"}), 500

    # AI 메시지 저장
    assistant_msg_id = str(uuid.uuid4())
    assistant_chat_data = {
        "msgId": assistant_msg_id,
        "msgSenderRole": "AI",
        "msgContent": ai_reply,
        "msgSentAt": sent_at_epoch,
        "msgSenderUUID": "AI-System",
        "parentMsgId": user_msg_id,
        "msgType": "T",
        "msgWorkspaceId": workspace_id
    }

    try:
        response_assistant = requests.post(f"{SPRING_BOOT_API_URL}/api/chat/save", json=assistant_chat_data,
                                           headers=headers)
        if response_assistant.status_code != 201:
            log.error(f"AI 메시지 저장 실패: {response_assistant.text}")
            return jsonify({"error": "AI 메시지 저장 실패"}), 500
    except Exception as e:
        log.error(f"AI 메시지 저장 중 오류: {e}")
        return jsonify({"error": f"AI 메시지 저장 중 오류: {e}"}), 500

    return jsonify({"reply": ai_reply, "workspaceId": workspace_id}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
