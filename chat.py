import openai
import os
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, app
from common_utils import token_required, log, g
import requests
import logging
from flask import Blueprint
from flask_cors import CORS
from openai import OpenAI

chat_blueprint = Blueprint("chat", __name__)
CORS(chat_blueprint,
     resources={r"/*": {"origins": "http://localhost:3000"}},
     supports_credentials=True)

# 환경 변수 로드
# 클라이언트 초기화
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")  # 환경 변수에서 API 키 로드
)
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")


# 로깅 초기화
def init_logging():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    return logger


# def get_workspace(current_user, token=None):
#     token = g.get("access_token", token)  # g.access_token에서 가져오기
#     refresh_token = request.headers.get("RefreshToken")  # RefreshToken 가져오기
#     headers = {
#         'Authorization': f'Bearer {token}',
#         'RefreshToken': refresh_token,  # RefreshToken 추가
#         'Content-Type': 'application/json'
#     }
#     workspace_check_url = f"{SPRING_BOOT_API_URL}/api/workspace/{current_user}"
#     log.info(f"Requesting workspace with headers: {headers}")
#     try:
#         response = requests.get(workspace_check_url, headers=headers)
#         log.info(f"Spring Boot response status: {response.status_code}")
#         log.info(f"Spring Boot response body: {response.text}")
#         if response.status_code == 200:
#             workspace_data = response.json().get("data", [])  # list 이기 때문에 data를 배열로 처리해야 한다.
#             if workspace_data:
#                 # 예시로 첫 번째 워크스페이스 ID 반환
#                 return workspace_data[0].get("workspaceId")
#             else:
#                 log.info("워크스페이스가 존재하지 않습니다.")
#                 return None
#         elif response.status_code == 401:
#             log.error("Spring Boot 서버에서 인증 실패: Invalid token")
#             raise Exception("Invalid token")
#         elif response.status_code == 404:
#             return None
#         else:
#             log.error(f"Spring Boot API 호출 중 오류: {response.text}")
#             raise Exception(f"Unexpected error during workspace retrieval: {response.text}")
#     except requests.RequestException as e:
#         log.error(f"워크스페이스 조회 실패: {e}")
#         raise Exception("Workspace retrieval error.")


# 채팅 세션 시작
def start_chat_session(workspace_id, current_user, headers):
    try:
        response = requests.post(
            f"{SPRING_BOOT_API_URL}/api/session/start",
            params={"workspaceId": workspace_id, "memUUID": current_user},
            headers=headers
        )
        if response.status_code != 201:
            log.error(f"채팅 세션 생성 실패: {response.text}")
            raise Exception("Chat session creation failed.")
    except Exception as e:
        log.error(f"채팅 세션 생성 에러: {e}")
        raise Exception("Chat session creation error.")


def create_workspace(current_user, user_message, ai_reply):
    token = g.get("access_token", None)  # g.access_token에서 토큰 가져오기
    refresh_token = request.headers.get("RefreshToken", "").split(" ")[1]

    try:
        # GPT 모델을 사용하여 워크스페이스 이름 생성
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system",
                 "content": "다음 사용자 메시지와 AI 응답을 바탕으로 간결한 한국어 워크스페이스 이름을 생성하세요."},
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": ai_reply},
            ]
        )
        workspace_name_first = response.choices[0].message.content.strip()
        if not workspace_name_first:
            raise ValueError("AI가 워크스페이스 이름 생성을 실패하였습니다.")

    except openai.OpenAIError as e:
        log.error(f"OpenAI API 호출 중 오류: {e}")
        raise Exception("AI를 사용한 워크스페이스 이름 생성 실패")
    except Exception as e:
        log.error(f"워크스페이스 이름 생성 실패: {e}")
        raise Exception("Workspace name generation failed.")

    # Spring Boot로 워크스페이스 저장
    headers = {
        'Authorization': f'Bearer {token}',
        'RefreshToken': f'Bearer {refresh_token}'  # RefreshToken 추가
    }

    params = {
        'memUuid': current_user,  # memUuid를 URL 파라미터로 전달
        'workspaceName': workspace_name_first  # 워크스페이스 이름
    }

    try:
        response = requests.post(f"{SPRING_BOOT_API_URL}/api/workspace/create", params=params, headers=headers)
        if response.status_code == 201:
            workspace_id = response.json().get("data", {}).get("workspaceId")

            # **채팅 세션 시작 호출**
            start_chat_session(workspace_id, current_user, headers)

            return workspace_id
        else:
            log.error(f"Workspace creation failed: {response.text}")
            raise Exception("Workspace creation failed.")
    except Exception as e:
        log.error(f"워크스페이스 저장 중 오류: {e}")
        raise Exception("Workspace creation error.")


#
# @chat_blueprint.route("/chat", methods=["OPTIONS"])
# def handle_preflight():
#     response = jsonify({"status": "OK"})
#     response.headers["Access-Control-Allow-Origin"] = "http://localhost:3000"
#     response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
#     response.headers["Access-Control-Allow-Headers"] = "Authorization, RefreshToken, Content-Type"
#     response.headers["Access-Control-Allow-Credentials"] = "true"
#     return response

# 세션 메시지 수 업데이트
def update_chat_session(workspace_id, headers):
    try:
        log.info(f"세션 메시지 업데이트 요청: workspaceId={workspace_id}, headers={headers}")
        response = requests.patch(
            f"{SPRING_BOOT_API_URL}/api/session/update-messages",
            params={"workspaceId": workspace_id},
            headers=headers
        )
        log.info(f"Spring Boot 응답: {response.status_code}, {response.text}")
        if response.status_code != 200:
            log.error(f"채팅 세션 업데이트 실패: {response.text}")
    except Exception as e:
        log.error(f"채팅 세션 업데이트 에러: {e}")


def register_routes(app):
    # Chat 엔드포인트
    @app.route("/chat", methods=["POST", "OPTIONS"])
    @token_required
    def chat(current_user=None):
        if request.method == "OPTIONS":
            response = jsonify({"status": "OK"})
            response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
            response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            response.headers.add("Access-Control-Allow-Headers", "Authorization, RefreshToken, Content-Type")
            response.headers.add("Access-Control-Allow-Credentials", "true")
            return response, 200
        elif request.method == "POST":
            data = request.json
            # 갱신된 Access Token, RefreshToken 가져오기
            token = g.get("access_token", None)
            refresh_token = g.get("refresh_token", None)

            # RefreshToken 헤더 가져오기
            # refresh_token_header = request.headers.get('RefreshToken', '')
            # refresh_token = refresh_token_header.split(' ')[1] if 'Bearer ' in refresh_token_header else None

            if not token or not refresh_token:
                return jsonify({"error": "Missing accessToken or refreshToken."}), 401

            user_message = request.json.get("message")
            create_workspace_flag = request.json.get("createWorkspace", False)  # 플래그 확인
            existing_workspace_id = request.json.get("workspaceId")  # 선택한 워크스페이스ID
            log.info(f"리액트에서 받은 워크스페이스ID: {existing_workspace_id}")
            workspace_id = None  # 초기화

            if not user_message:
                return jsonify({"error": "No message provided."}), 400

            # 워크스페이스 조회 또는 생성
            try:
                if create_workspace_flag:
                    ai_reply = "처음 메시지입니다. AI 응답이 준비되었습니다."
                    # 워크스페이스 생성
                    workspace_id = create_workspace(current_user, user_message, ai_reply)
                else:
                    # 기존 워크스페이스 조회
                    workspace_id = existing_workspace_id
                    if not workspace_id:
                        return jsonify({"error": "워크스페이스가 없습니다."}), 404
            except Exception as e:
                log.error(f"Workspace error: {e}")
                return jsonify({"error": "Workspace creation or retrieval failed"}), 500


            # 이후 코드에서 workspaceId를 사용
            # 사용자 메시지 저장 및 AI 응답 로직은 그대로 유지
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
                'Authorization': f'Bearer {token}',  # g.access_token 사용
                'RefreshToken': f'Bearer {refresh_token}'  # RefreshToken 추가
            }

            try:
                response_user = requests.post(f"{SPRING_BOOT_API_URL}/api/chat/save", json=user_chat_data,
                                              headers=headers)

                if response_user.status_code == 201:
                    # ** 세션 메시지 수 업데이트 **
                    update_chat_session(user_chat_data["msgWorkspaceId"], headers)
                else:
                    log.error(f"사용자 메시지 저장 실패: {response_user.text}")
                    return jsonify({"error": "사용자 메시지 저장 실패"}), 500
            except Exception as e:
                log.error(f"사용자 메시지 저장 중 오류: {e}")
                return jsonify({"error": f"사용자 메시지 저장 중 오류: {e}"}), 500

            # AI 응답 생성
            try:
                response = client.chat.completions.create(
                    model="gpt-4-turbo",
                    messages=[
                        {"role": "system",
                         "content": "당신은 친절하고 공감 능력이 뛰어난 AI 비서입니다. 대화 상대가 어르신이기 때문에 항상 공손하고 따뜻한 한국어로만 대답하세요."},
                        {"role": "user", "content": user_message}
                    ]
                )
                # 응답 메시지 추출
                ai_reply = response.choices[0].message.content.strip()
                if not ai_reply:
                    raise ValueError("AI 응답이 비어 있습니다. 다시 시도해주세요.")
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
                if response_assistant.status_code == 201:
                    # **세션 메시지 수 업데이트**
                    update_chat_session(assistant_chat_data["msgWorkspaceId"], headers)
                else:
                    log.error(f"AI 메시지 저장 실패: {response_assistant.text}")
                    return jsonify({"error": "AI 메시지 저장 실패"}), 500
            except Exception as e:
                log.error(f"AI 메시지 저장 중 오류: {e}")
                return jsonify({"error": f"AI 메시지 저장 중 오류: {e}"}), 500

            return jsonify({"reply": ai_reply, "workspaceId": workspace_id}), 200
