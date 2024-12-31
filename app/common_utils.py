import base64
import jwt
import logging
from functools import wraps
from flask import request, jsonify, g
from dotenv import load_dotenv
import os
import requests


# 로깅 초기화
def init_logging():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    return logger


log = init_logging()

# 환경 변수 로드
load_dotenv()
SECRET_KEY_BASE64 = os.getenv("JWT_SECRET_KEY")
SECRET_KEY = base64.b64decode(SECRET_KEY_BASE64)
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")


# JWT 디코딩 함수
def decode_jwt(token):
    """
    JWT 토큰을 디코딩합니다.
    """
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded_token
    except jwt.ExpiredSignatureError:
        log.warning("Access Token has expired. Attempting to refresh...")
        return "expired"
    except jwt.InvalidTokenError:
        log.error("Invalid JWT token")
        return None


# Access Token 갱신 함수
def refresh_access_token(refresh_token, access_token):
    """
    Access Token이 만료된 경우 새로 갱신합니다.
    """
    refresh_url = f"{SPRING_BOOT_API_URL}/reissue"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'RefreshToken': f'Bearer {refresh_token}',
        'extendLogin': 'true'
    }
    try:
        response = requests.post(refresh_url, headers=headers)
        if response.status_code == 200:
            new_access_token = response.headers.get("Authorization").split(" ")[1]
            log.info("Access Token successfully refreshed.")
            return new_access_token
        else:
            log.error(f"Access Token refresh failed: {response.text}")
            return None
    except requests.RequestException as e:
        log.error(f"Error refreshing Access Token: {e}")
        return None


# JWT 인증 데코레이터
def token_required(f):
    """
    API 요청을 인증하기 위한 JWT 데코레이터.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        # 헤더에서 Access Token 가져오기
        token = request.headers.get('Authorization', '').replace("Bearer ", "")
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            data = decode_jwt(token)

            if data == "expired":
                # Refresh Token으로 Access Token 갱신
                refresh_token = request.headers.get("RefreshToken", "").replace("Bearer ", "")
                if not refresh_token:
                    return jsonify({'message': 'Refresh token is missing!'}), 401

                new_token = refresh_access_token(refresh_token, token)
                if not new_token:
                    raise Exception("Failed to refresh Access Token")

                # 갱신된 Access Token을 저장하고 디코딩
                g.access_token = new_token
                data = decode_jwt(new_token)
            else:
                g.access_token = token

            # 토큰 검증 실패 처리
            if not data:
                raise Exception("Invalid token")

            # 사용자 정보 확인
            member = data.get("member")
            if not member or "memUUID" not in member:
                raise Exception("Invalid token: Missing member information")

            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token validation error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(current_user, *args, **kwargs)

    return decorated
