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
        'RefreshToken': f'Bearer {refresh_token}',  # refresh_token
        'extendLogin': 'true'
    }
    try:
        response = requests.post(refresh_url, headers=headers)
        log.info(f"/reissue 응답 코드: {response.status_code}, 응답: {response.text}")
        if response.status_code == 200:
            new_access_token = None
            new_refresh_token = None
            log.info(f"갱신된 Access Token: {new_access_token},\n갱신된 Refresh Token: {new_refresh_token}")

            # Authorization 헤더 확인 및 처리
            auth_header = response.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                new_access_token = auth_header.split(" ")[1]
            else:
                new_access_token = f"Bearer {auth_header}"

            # RefreshToken 헤더 확인 및 처리
            refresh_header = response.headers.get("RefreshToken", "")
            if refresh_header.startswith("Bearer "):
                new_refresh_token = refresh_header.split(" ")[1]
            else:
                new_refresh_token = f"Bearer {refresh_header}"

            if new_access_token and new_refresh_token:
                log.info(f"갱신된 Access Token: {new_access_token},\n갱신된 Refresh Token: {new_refresh_token}")
                return new_access_token, new_refresh_token
            else:
                log.error("갱신된 토큰을 가져오는 데 실패했습니다.")
                return None, None
    except requests.RequestException as e:
        log.error(f"Error refreshing Access Token: {e}")
        return None, None


def token_required(f):
    """JWT 인증 데코레이터"""

    @wraps(f)
    def decorated(*args, **kwargs):
        # OPTIONS 요청은 인증 없이 통과
        if request.method == "OPTIONS":
            return f(*args, **kwargs)

        # Authorization 및 RefreshToken 헤더 가져오기
        token = request.headers.get('Authorization', '').replace("Bearer ", "")
        refresh_token = request.headers.get("RefreshToken", "").replace("Bearer ", "")

        log.info(f"Received Tokens - Access Token: {token}, \n Refresh Token: {refresh_token}")

        # 토큰 유효성 검사
        if not token:
            return jsonify({'message': 'Access token is missing!'}), 401
        if not refresh_token:
            return jsonify({'message': 'Refresh token is missing!'}), 401

        try:
            # JWT 디코드
            data = decode_jwt(token)
            log.info(f"갱신되기 전 Access Token 상태: {data if data else '유효하지 않음'}")

            # Access Token이 만료된 경우
            if data == "expired":
                log.info("Access Token이 만료되었습니다. Refresh Token으로 갱신을 시도합니다.")
                new_access_token, new_refresh_token = refresh_access_token(refresh_token, token)
                if not new_access_token or not new_refresh_token:
                    raise Exception("Failed to refresh Access Token")

                # 갱신된 토큰 저장
                g.access_token = new_access_token
                g.refresh_token = new_refresh_token

                # 갱신된 토큰 재검증
                data = decode_jwt(new_access_token)
                log.info(f"갱신된 Access Token 상태: {data if data else '유효하지 않음'}")
                log.info(f"갱신된 g.Access Tokenm g.Refresh Token:\n{g.access_token}, \nRefresh Token: {g.refresh_token}")
                if not data:
                    raise Exception("Invalid refreshed token")
            else:
                log.info("Access Token이 유효합니다.")

                # 기존 Access Token 사용
                g.access_token = token
                g.refresh_token = refresh_token

            # 사용자 정보 추출
            member = data.get("member")
            log.info(f"Decoded member info: {member}")
            if not member or "memUUID" not in member:
                log.error("Invalid member information in token.")
                raise Exception("Missing member information")
            current_user = member["memUUID"]
        except Exception as e:
            log.error(f"Token validation error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401

        # 인증된 사용자 정보와 함께 원래 함수 호출
        return f(current_user, *args, **kwargs)

    return decorated
