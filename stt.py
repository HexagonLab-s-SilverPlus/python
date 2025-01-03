from flask import Blueprint, request, jsonify
from flask_cors import CORS
from common_utils import log
import speech_recognition as sr
from pydub import AudioSegment
from io import BytesIO


# Blueprint 생성
stt_blueprint = Blueprint("stt", __name__)

# CORS 설정
CORS(stt_blueprint, resources={r"/*": {"origins": ["http://localhost:3000", "http://localhost"]}})

# 경로 정의
@stt_blueprint.route("/pagerider", methods=["POST"])
def process_audio():
    '''
    음성 데이터를 google STT를 사용해 텍스트로 변환하고 React로 반환
    '''
    # 요청에서 음성 파일 가져오기
    if 'audio' not in request.files:
        log.error("오디오 파일이 제공되지 않았습니다.")
        return jsonify({"error": "제공된 오디오 파일이 없습니다."}), 400

    audio_file = request.files['audio']

    # 로그 추가: 파일 정보 출력
    log.info(f"Received audio file: {audio_file.filename}, Content-Type: {audio_file.content_type}")

    try:
        # Blob 데이터를 WAV 포맷으로 변환
        audio_data = BytesIO(audio_file.read())
        audio_segment = AudioSegment.from_file(audio_data, format="wav")
        wav_data = BytesIO()
        audio_segment.export(wav_data, format="wav")
        wav_data.seek(0)

        # STT 처리
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_data) as source:
            audio = recognizer.record(source)
            recognized_text = recognizer.recognize_google(audio, language='ko-KR')
            log.info(f"Recognized text: {recognized_text}")
    except sr.UnknownValueError:
        # Google STT가 음성을 인식하지 못한 경우
        log.error("Google STT가 음성을 인식하지 못했습니다.")
        return jsonify({"error": "음성을 인식하지 못했습니다."}), 400  # 400 Bad Request 반환
    except sr.RequestError as e:
        # Google STT 서비스 요청 중 오류 발생
        log.error(f"Google STT 요청 오류: {e}")
        return jsonify({"error": "STT 서비스 요청 오류가 발생했습니다."}), 500  # 500 Internal Server Error 반환
    except Exception as e:
        # 그 외 예기치 못한 오류 처리
        log.error(f"오류가 발생하였습니다: {e}")
        return jsonify({"error": "오류가 발생하였습니다."}), 500  # 500 Internal Server Error 반환


    # React로 텍스트 반환
    return jsonify({"recognized_text": recognized_text}), 200

# Blueprint 등록 함수 추가
def register_routes(app):
    """
    Flask 앱에 STT 관련 경로를 등록하는 함수.
    """
    app.register_blueprint(stt_blueprint, url_prefix="/stt")
