import base64
import jwt
import requests
import logging
from functools import wraps
from flask import request, jsonify, g
from dotenv import load_dotenv
import os

# 로깅 설정
log = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()
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
        return "expired"
    except jwt.InvalidTokenError:
        log.error("Invalid JWT")
        return None


# Access Token 갱신 함수
def refresh_access_token(refresh_token, access_token):
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

                new_token = refresh_access_token(refresh_token, access_token=token)
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
                raise Exception("Invalid token: Missing member information")
            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token validation error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user, *args, **kwargs)

    return decorated
