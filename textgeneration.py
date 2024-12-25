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
from flask import Flask, request, jsonify, g

# Flask 초기 설정
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000"]}},
     allow_headers=["Authorization", "Refreshtoken", "Content-Type"])

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
        log.warning("Access Token has expired. Attempting to refresh...")
        return "expired"  # 만료된 상태를 반환
    except jwt.InvalidTokenError:
        log.error("Invalid JWT")
        return None


# Access Token 갱신 함수 추가
# Spring Boot 서버를 호출하여 새로운 Access Token을 발급받는 로직을 추가한다.
def refresh_access_token(refresh_token, access_token):
    refresh_url = f"{SPRING_BOOT_API_URL}/reissue"
    headers = {
        'Authorization': f'Bearer {access_token}',  # Access Token
        'RefreshToken': f'Bearer {refresh_token}',  # Refresh Token
        'extendLogin': 'true'  # 로그인 연장 여부
    }
    try:
        response = requests.post(refresh_url, headers=headers)
        if response.status_code == 200:
            # 새로 발급된 Access Token 반환
            new_access_token = response.headers.get("Authorization").split(" ")[1]
            log.info("Access Token successfully refreshed.")
            return new_access_token  # 새로 발급된 AccessToken
        else:
            log.error(f"Access Token refresh failed: {response.text}")
            return None
    except requests.RequestException as e:
        log.error(f"Error refreshing Access Token: {e}")
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
            if data == "expired":
                refresh_token_header = request.headers.get("RefreshToken", "")
                refresh_token = (
                    refresh_token_header.split(" ")[1]
                    if "Bearer " in refresh_token_header
                    else None
                )
                if not refresh_token:
                    return jsonify({'message': 'Refresh token is missing!'}), 401

                # Spring Boot 서버를 호출하여 Access Token 갱신
                new_token = refresh_access_token(refresh_token, access_token=token)
                if not new_token:
                    raise Exception("Failed to refresh Access Token")

                # 새로 발급받은 토큰을 글로벌 컨텍스트에 저장
                g.access_token = new_token
                data = decode_jwt(new_token)
            else:
                g.access_token = token  # 기존 유효한 토큰을 저장

            if not data:
                raise Exception("Invalid token")
            member = data.get("member")
            if not member or "memUUID" not in member:
                raise Exception("Invalid token: Missing member information")
            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token validation error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user, *args, **kwargs)

    return decorated

def get_workspace(current_user, token=None):
    token=g.get("access_token", token) # g.access_token에서 가져오기
    refresh_token = request.headers.get("RefreshToken")  # RefreshToken 가져오기
    headers = {
        'Authorization': f'Bearer {token}',
        'RefreshToken': refresh_token,  # RefreshToken 추가
        'Content-Type': 'application/json'
    }
    workspace_check_url = f"{SPRING_BOOT_API_URL}/api/workspace/{current_user}"
    log.info(f"Requesting workspace with headers: {headers}")
    try:
        response = requests.get(workspace_check_url, headers=headers)
        log.info(f"Spring Boot response status: {response.status_code}")
        log.info(f"Spring Boot response body: {response.text}")
        if response.status_code == 200:
            workspace_data = response.json().get("data", [])  # list 이기 때문에 data를 배열로 처리해야 한다.
            if workspace_data:
                # 예시로 첫 번째 워크스페이스 ID 반환
                return workspace_data[0].get("workspaceId")
            else:
                log.info("워크스페이스가 존재하지 않습니다.")
                return None
        elif response.status_code == 401:
            log.error("Spring Boot 서버에서 인증 실패: Invalid token")
            raise Exception("Invalid token")
        elif response.status_code == 404:
            return None
        else:
            log.error(f"Spring Boot API 호출 중 오류: {response.text}")
            raise Exception(f"Unexpected error during workspace retrieval: {response.text}")
    except requests.RequestException as e:
        log.error(f"워크스페이스 조회 실패: {e}")
        raise Exception("Workspace retrieval error.")


def create_workspace(current_user, user_message, ai_reply):
    token = g.get("access_token", None) # g.access_token에서 토큰 가져오기
    refresh_token=request.headers.get("RefreshToken","").split(" ")[1]

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
    headers = {
        'Authorization': f'Bearer {token}',
        'RefreshToken': f'Bearer {refresh_token}'  # RefreshToken 추가
    }
    # 스프링부트의 /api/workspace/create는 @RequestParam으로 데이터를 받으므로,
    # Flask에서 데이터를 URL 파라미터로 형식으로 전송해야 한다. (JSON 형식 X)
    # workspace_data = {"memUuid": current_user, "workspaceName": workspace_name}

    params = {
        'memUuid': current_user,  # memUuid를 URL 파라미터로 전달
        'workspaceName': workspace_name  # 워크스페이스 이름
    }
    try:
        response = requests.post(f"{SPRING_BOOT_API_URL}/api/workspace/create", params=params, headers=headers)
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
    # 갱신된 Access Token 가져오기
    token = g.get("access_token", None)

    # RefreshToken 헤더 가져오기
    refresh_token_header = request.headers.get('RefreshToken', '')
    refresh_token = refresh_token_header.split(' ')[1] if 'Bearer ' in refresh_token_header else None

    if not token or not refresh_token:
        return jsonify({"error": "Missing accessToken or refreshToken."}), 401

    user_message = request.json.get("message")
    create_workspace_flag = request.json.get("createWorkspace", False)  # 플래그 확인
    if not user_message:
        return jsonify({"error": "No message provided."}), 400

    # 워크스페이스 조회 또는 생성
    try:
        if create_workspace_flag:
            ai_reply = "처음 메시지입니다. AI 응답이 준비되었습니다."
            workspace_id = create_workspace(current_user, user_message, ai_reply)
        else:
            # 기존 워크스페이스 조회
            workspace_id = get_workspace(current_user, token)
            if not workspace_id:
                return jsonify({"error": "워크스페이스가 없습니다."}), 404
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

    headers = {
        'Authorization': f'Bearer {token}', # g.access_token 사용
        'RefreshToken': f'Bearer {refresh_token}'  # RefreshToken 추가
    }

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
        "msgSenderUUID": "ai-uuid-1234-5678-90ab-cdef12345678",
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
