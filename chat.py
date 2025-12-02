from io import BytesIO

import openai
import os
import uuid
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, app, Response
from common_utils import token_required, log, g
import requests
import logging
from flask import Blueprint
from flask_cors import CORS
from openai import OpenAI
from sentiment_analysis import analyze_sentiment  # 감정 분석 함수 import

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
            model="gpt-4o-mini",
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
    # Background message saving function
    def save_message_background(api_url, chat_data, headers, workspace_id):
        """백그라운드에서 메시지를 저장하는 함수"""
        try:
            response = requests.post(f"{api_url}/api/chat/save", json=chat_data, headers=headers)
            if response.status_code == 201:
                update_chat_session(workspace_id, headers)
            else:
                log.error(f"메시지 저장 실패: {response.text}")
        except Exception as e:
            log.error(f"메시지 저장 중 오류: {e}")

    # TTS 엔드포인트 - 별도로 분리하여 React에서 텍스트 표시 후 TTS 로드 가능
    @app.route("/chat/tts", methods=["POST", "OPTIONS"])
    @token_required
    def chat_tts(current_user=None):
        """TTS 생성 엔드포인트 - 텍스트를 받아 음성 생성"""
        if request.method == "OPTIONS":
            response = jsonify({"status": "OK"})
            response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
            response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            response.headers.add("Access-Control-Allow-Headers", "Authorization, RefreshToken, Content-Type")
            response.headers.add("Access-Control-Allow-Credentials", "true")
            return response, 200

        text = request.json.get("text")
        if not text:
            return jsonify({"error": "No text provided."}), 400

        try:
            audio_base64 = generate_tts(text)
            return jsonify({"audioBase64": audio_base64}), 200
        except Exception as e:
            log.error(f"TTS 생성 실패: {e}")
            return jsonify({"error": "TTS 생성 중 오류"}), 500

    # 스트리밍 Chat 엔드포인트
    @app.route("/chat/stream", methods=["POST", "OPTIONS"])
    @token_required
    def chat_stream(current_user=None):
        """스트리밍 방식의 Chat 엔드포인트 - 실시간으로 응답 전송"""
        if request.method == "OPTIONS":
            response = jsonify({"status": "OK"})
            response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
            response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            response.headers.add("Access-Control-Allow-Headers", "Authorization, RefreshToken, Content-Type")
            response.headers.add("Access-Control-Allow-Credentials", "true")
            return response, 200

        data = request.json
        token = g.get("access_token", None)
        refresh_token = g.get("refresh_token", None)

        if not token or not refresh_token:
            return jsonify({"error": "Missing accessToken or refreshToken."}), 401

        user_message = data.get("message")
        create_workspace_flag = data.get("createWorkspace", False)
        existing_workspace_id = data.get("workspaceId")
        workspace_id = None

        if not user_message:
            return jsonify({"error": "No message provided."}), 400

        # 워크스페이스 처리
        try:
            if create_workspace_flag:
                ai_reply_temp = "처음 메시지입니다. AI 응답이 준비되었습니다."
                workspace_id = create_workspace(current_user, user_message, ai_reply_temp)
            else:
                workspace_id = existing_workspace_id
                if not workspace_id:
                    return jsonify({"error": "워크스페이스가 없습니다."}), 404
        except Exception as e:
            log.error(f"Workspace error: {e}")
            return jsonify({"error": "Workspace creation or retrieval failed"}), 500

        # 사용자 메시지 데이터 준비
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
            'Authorization': f'Bearer {token}',
            'RefreshToken': f'Bearer {refresh_token}'
        }

        # 사용자 메시지 백그라운드 저장
        user_save_thread = threading.Thread(
            target=save_message_background,
            args=(SPRING_BOOT_API_URL, user_chat_data, headers, workspace_id)
        )
        user_save_thread.start()

        # 감정 분석
        try:
            emotion = analyze_sentiment(user_message)
        except Exception as e:
            log.error(f"감정 분석 실패: {e}")
            emotion = "중립"

        def generate_stream():
            """스트리밍 응답 생성기"""
            full_response = []
            try:
                # 스트리밍으로 GPT 호출
                stream_response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system",
                         "content": "당신은 친절하고 공감 능력이 뛰어난 AI 비서입니다. 대화 상대가 어르신이기 때문에 항상 공손하고 따뜻한 한국어로만 대답하세요."
                                    f"사용자의 감정은 '{emotion}'입니다. 이 감정을 고려하여 답변을 작성하세요."},
                        {"role": "user", "content": user_message}
                    ],
                    stream=True
                )

                # 첫 번째로 workspace_id 전송
                yield f"data: {{\"type\": \"workspace\", \"workspaceId\": \"{workspace_id}\"}}\n\n"

                for chunk in stream_response:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response.append(content)
                        # SSE 형식으로 전송
                        import json
                        yield f"data: {{\"type\": \"content\", \"content\": {json.dumps(content)}}}\n\n"

                # 완료 신호 전송
                yield f"data: {{\"type\": \"done\"}}\n\n"

                # AI 메시지 백그라운드 저장
                ai_reply = "".join(full_response)
                if ai_reply:
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
                    ai_save_thread = threading.Thread(
                        target=save_message_background,
                        args=(SPRING_BOOT_API_URL, assistant_chat_data, headers, workspace_id)
                    )
                    ai_save_thread.start()

            except Exception as e:
                log.error(f"스트리밍 응답 생성 실패: {e}")
                import json
                yield f"data: {{\"type\": \"error\", \"message\": {json.dumps(str(e))}}}\n\n"

        response = Response(generate_stream(), mimetype='text/event-stream')
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        response.headers.add("Access-Control-Allow-Credentials", "true")
        response.headers.add("Cache-Control", "no-cache")
        response.headers.add("X-Accel-Buffering", "no")
        return response

    # 기존 Chat 엔드포인트 (비스트리밍 - 하위 호환성 유지, TTS 분리 및 백그라운드 저장 적용)
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

            if not token or not refresh_token:
                return jsonify({"error": "Missing accessToken or refreshToken."}), 401

            user_message = request.json.get("message")
            create_workspace_flag = request.json.get("createWorkspace", False)
            existing_workspace_id = request.json.get("workspaceId")
            # TTS 생성 여부 (기본값 False - 클라이언트가 별도로 /chat/tts 호출)
            include_tts = request.json.get("includeTts", False)
            log.info(f"리액트에서 받은 워크스페이스ID: {existing_workspace_id}")
            workspace_id = None

            if not user_message:
                return jsonify({"error": "No message provided."}), 400

            # 워크스페이스 조회 또는 생성
            try:
                if create_workspace_flag:
                    ai_reply = "처음 메시지입니다. AI 응답이 준비되었습니다."
                    workspace_id = create_workspace(current_user, user_message, ai_reply)
                else:
                    workspace_id = existing_workspace_id
                    if not workspace_id:
                        return jsonify({"error": "워크스페이스가 없습니다."}), 404
            except Exception as e:
                log.error(f"Workspace error: {e}")
                return jsonify({"error": "Workspace creation or retrieval failed"}), 500

            # 사용자 메시지 데이터 준비
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
                'Authorization': f'Bearer {token}',
                'RefreshToken': f'Bearer {refresh_token}'
            }

            # 사용자 메시지 백그라운드 저장
            user_save_thread = threading.Thread(
                target=save_message_background,
                args=(SPRING_BOOT_API_URL, user_chat_data, headers, workspace_id)
            )
            user_save_thread.start()

            # AI 응답 생성
            try:
                # 감정 분석 및 AI 응답 생성
                emotion = analyze_sentiment(user_message)

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system",
                         "content": "당신은 친절하고 공감 능력이 뛰어난 AI 비서입니다. 대화 상대가 어르신이기 때문에 항상 공손하고 따뜻한 한국어로만 대답하세요."
                                    f"사용자의 감정은 '{emotion}'입니다. 이 감정을 고려하여 답변을 작성하세요."},
                        {"role": "user", "content": user_message}
                    ]
                )
                ai_reply = response.choices[0].message.content.strip()
                if not ai_reply:
                    raise ValueError("AI 응답이 비어 있습니다. 다시 시도해주세요.")

            except Exception as e:
                log.error(f"AI 응답 생성 실패: {e}")
                return jsonify({"error": "AI 응답 생성 중 오류"}), 500

            # AI 메시지 백그라운드 저장
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

            ai_save_thread = threading.Thread(
                target=save_message_background,
                args=(SPRING_BOOT_API_URL, assistant_chat_data, headers, workspace_id)
            )
            ai_save_thread.start()

            # 응답 구성 (TTS는 선택적으로 포함)
            response_data = {"reply": ai_reply, "workspaceId": workspace_id}

            if include_tts:
                try:
                    audio_base64 = generate_tts(ai_reply)
                    response_data["audioBase64"] = audio_base64
                except Exception as e:
                    log.error(f"TTS 생성 실패: {e}")
                    # TTS 실패해도 텍스트 응답은 반환

            return jsonify(response_data), 200




from gtts import gTTS
import base64

def generate_tts(ai_reply):
    """
    AI 응답 텍스트를 기반으로 TTS 음성을 생성하여 Base64 인코딩된 문자열로 반환합니다.
    """
    try:
        tts = gTTS(ai_reply, lang="ko")
        audio_data = BytesIO()
        tts.write_to_fp(audio_data)
        audio_data.seek(0)  # 스트림의 시작으로 이동

        # Base64 인코딩
        audio_base64 = base64.b64encode(audio_data.read()).decode("utf-8")
        return audio_base64
    except Exception as e:
        log.error(f"TTS 생성 실패: {e}")
        raise Exception("TTS 생성 중 오류가 발생했습니다.")