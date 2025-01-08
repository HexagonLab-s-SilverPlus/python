"""
작성자: 최은영
- ****절대 수정하지 마세요****
- Flask에서 토큰 관리하는 파일
- Flask에서 토큰 이슈 있으면 팀장한테 물어보세요😎
"""


import base64
import jwt
import logging
from functools import wraps
from flask import request, jsonify, g
import os
import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)


# 로깅 초기화
def init_logging():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    return logger


init_logging()

# 환경 변수 로드
load_dotenv()
SECRET_KEY_BASE64 = os.getenv("JWT_SECRET_KEY")
SECRET_KEY = base64.b64decode(SECRET_KEY_BASE64)
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")


def decode_jwt(token):
    """JWT 토큰 디코딩"""
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded_token
    except jwt.ExpiredSignatureError:
        log.warning("Access Token expired.")
        return {"error": "expired"}
    except jwt.InvalidTokenError:
        return {"error": "invalid"}




def prepare_token(token):
    """Bearer 포맷으로 정리된 토큰 반환"""
    if not token or not token.strip():
        raise ValueError("Invalid token: Token is missing or empty")
    return f"Bearer {token.strip()}"



def refresh_access_token(refresh_token, access_token):
    """Access Token 갱신"""
    if not refresh_token or not refresh_token.strip():
        log.error("Refresh Token is missing or empty. Cannot refresh access token.")
        return None

    refresh_url = f"{SPRING_BOOT_API_URL}/reissue"
    headers = {
        'Authorization': prepare_token(access_token),
        "RefreshToken": f"Bearer {refresh_token}" if refresh_token.strip() else None,
        'extendLogin': 'true'
    }
    if not refresh_token.strip():
        log.warning("RefreshToken is empty. Check why it's not set properly.")

    try:
        response = requests.post(refresh_url, headers=headers)
        if response.status_code == 200:
            auth_header = response.headers.get("Authorization", "")
            # Authorization 헤더 확인 및 처리
            if auth_header.startswith("Bearer "):
                return auth_header.split(" ")[1]
            log.error("Reissue response does not contain a valid Authorization header.")
        else:
            log.error(f"Failed to refresh token. Response: {response.text}")
    except requests.RequestException as e:
        log.error(f"Error refreshing Access Token: {e}")

    return None


def token_required(f):
    """JWT 인증 데코레이터"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # OPTIONS 요청은 인증 없이 통과
        if request.method == "OPTIONS":
            return f(*args, **kwargs)

        # Authorization 및 RefreshToken 헤더 가져오기
        access_token = request.headers.get('Authorization', '').replace("Bearer ", "")
        refresh_token = request.headers.get("RefreshToken", '').replace("Bearer ", "")

        log.info(f"Received Tokens - Access Token: {access_token}, Refresh Token: {refresh_token}")

        # 토큰 유효성 검사
        if not access_token:
            return jsonify({'message': 'Access token is missing!'}), 401
        if not refresh_token:
            log.warning("Refresh token is missing or empty!")
            return jsonify({'message': 'Refresh token is missing!'}), 401

        try:
            # Access Token 디코드
            data = decode_jwt(access_token)

            # 오류 반환 처리
            if "error" in data:
                if data["error"] == "expired":
                    log.info("Access Token이 만료되었습니다. Refresh Token으로 갱신을 시도합니다.")
                    new_access_token = refresh_access_token(refresh_token, access_token)
                    if not new_access_token:
                        return jsonify({'message': 'Failed to refresh Access Token!'}), 401
                    g.access_token = new_access_token

                    # 갱신된 Access Token으로 다시 디코딩
                    data = decode_jwt(new_access_token)
                    if "error" in data:
                        return jsonify({'message': 'Invalid Access Token after refresh!'}), 401
                else:
                    return jsonify({'message': 'Invalid Access Token!'}), 401
            else:
                g.access_token = access_token

            g.refresh_token = refresh_token
            # 사용자 정보 추출
            member = data.get("member")
            log.info(f"Decoded member info: {member}")
            if not member or "memUUID" not in member:
                log.error("Invalid member information in token.")
                return jsonify({'message': 'Invalid member information!'}), 401

            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token validation error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401

        # 인증된 사용자 정보와 함께 원래 함수 호출
        return f(current_user, *args, **kwargs)

    return decorated
