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
        return "expired"
    except jwt.InvalidTokenError:
        log.error("Invalid JWT token.")
        return None

def refresh_access_token(refresh_token, access_token):
    """Access Token 갱신"""
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
            log.info("Access Token refreshed.")
            return new_access_token
        else:
            log.error(f"Access Token refresh failed: {response.text}")
            return None
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

        # Authorization 헤더 확인
        token = request.headers.get('Authorization', '').replace("Bearer ", "")
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            # JWT 디코드 및 검증 로직
            data = decode_jwt(token)

            if data == "expired":
                # Refresh Token으로 갱신
                refresh_token = request.headers.get("RefreshToken", "").replace("Bearer ", "")
                if not refresh_token:
                    return jsonify({'message': 'Refresh token is missing!'}), 401

                new_token = refresh_access_token(refresh_token, token)
                if not new_token:
                    raise Exception("Failed to refresh Access Token")

                g.access_token = new_token
                data = decode_jwt(new_token)
            else:
                g.access_token = token

            if not data:
                raise Exception("Invalid token")

            member = data.get("member")
            if not member or "memUUID" not in member:
                raise Exception("Missing member information")

            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token validation error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(current_user, *args, **kwargs)
    return decorated
