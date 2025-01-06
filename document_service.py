import csv
import openai
from docx import Document
import os
from flask import request, jsonify, send_file, Blueprint
from common_utils import token_required, log  # 공통 코드에서 가져옴
import json
import requests
import uuid
from flask_cors import CORS

# NAS 공유 폴더 접근
FTP_SERVER = "ktj0514.synology.me"
FTP_PORT = 21
FTP_USERNAME = "anonymous"
FTP_PASSWORD = "anonymous@"
FTP_REMOTE_DIR = "files/document"

# 폴더 생성
os.makedirs("processed", exist_ok=True)

# Flask Blueprint 생성
doc_blueprint = Blueprint("chat", __name__)
CORS(doc_blueprint,
     resources={r"/*": {"origins": "http://localhost:3000"}},
     supports_credentials=True)

# 환경 변수 로드
openai.api_key = os.getenv("OPENAI_API_KEY")
SPRING_BOOT_API_URL = os.getenv("SPRING_BOOT_API_URL")


def register_routes(app):
    def generate_questions(document_type):
        """
        GPT를 활용하여 전입신고서 작성에 필요한 질문과 키를 자동 생성
        """
        prompt = f"""
            "{document_type}" 작성을 위해 필요한 정보를 수집하려고 합니다.
질문과 질문에 해당하는 키 값을 아래 JSON 형식으로 반환해주세요:
[
    {{"key": "unique_key_for_question1", "question": "질문1"}},
    {{"key": "unique_key_for_question2", "question": "질문2"}}
]
JSON 형식 외에는 추가적인 설명을 포함하지 마세요.
        """
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": "너는 한국 정부 문서 작성의 전문가입니다."},
                    {"role": "user", "content": prompt}
                ]
            )
            if not response.choices[0].message['content']:
                log.error("GPT 응답이 비어 있습니다.")
                return []
            questions_json = response.choices[0].message['content']

            questions_with_keys = json.loads(questions_json)
            return questions_with_keys

        except json.JSONDecodeError as e:
            log.error(f"JSON 파싱 오류: {e}")
            log.error(f"GPT 응답 내용: {questions_json}")
            return []
        except openai.error.OpenAIError as e:
            log.error(f"OpenAI API 호출 중 오류: {e}")
            return []
        except Exception as e:
            log.error(f"예기치 못한 오류: {e}")
            return []

    def generate_csv_and_upload(responses, document_type):
        """
          1. CSV 파일 생성
          2. DOCUMENT 및 DOC_FILE 테이블 데이터 전송
        """
        try:
            # CSV 파일 생성
            csv_filename=f"{document_type}_{uuid.uuid4().hex}.csv"
            csv_path=os.path.join("processed", csv_filename)
            with open(csv_path, mode='w', newline='', encoding='utf-8-sig') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["Key", "Value"])  # 헤더 추가
                for key, value in responses.items():
                    writer.writerow([key, value])
            log.info(f"CSV 파일 생성 완료: {csv_path}")

            # DOCUMENT 저장
            document_id = str(uuid.uuid4())
            document_payload={
                "docId": document_id,
                "docType": document_type,
                "docCreateAt": "2025-01-06T10:00:00",  # 현재 시간 사용 가능
                "isApproved": None,
                "writtenBy": "작성자_UUID",  # 사용자 ID
                "apprvedAt": None,
                "approvedBy": None
            }
            document_response = requests.post(f"{SPRING_BOOT_API_URL}/api/document", json=document_payload)
            document_response.raise_for_status()
            log.info(f"DOCUMENT 저장 완료: {document_response.json()}")


            # DOC_FILE 저장 및 NAS 업로드
            with open(csv_path, "rb") as file_stream:
                doc_file_payload={"docId": document_id} # docId는 요청의 @RequestParam으로 사용됨
                files={
                    "file": (csv_filename, file_stream, "text/csv") # file은 요청의 @RequestParam으로 사용됨
                }
                # Multipart/form-data로 Spring Boot API 호출
                doc_file_response = requests.post(
                    f"{SPRING_BOOT_API_URL}/api/doc-files",
                    data=doc_file_payload, # key-value 데이터
                    files=files # 업로드할 파일
                )
                doc_file_response.raise_for_status() # HTTP 에러 확인
                log.info(f"DOC_FILE 저장 및 NAS 업로드 완료: {doc_file_response.json()}")

            return {"documentId": document_id, "csvPath": csv_path}

        except requests.RequestException as e:
            log.error(f"Spring Boot API 요청 중 오류: {e}")
            return None
        except Exception as e:
            log.error(f"파일 처리 중 예기치 못한 오류 발생: {e}")
            return None


    def set_cors_headers(response):
        """
        CORS 헤더 설정
        """
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.headers.add("Access-Control-Allow-Headers", "Authorization, RefreshToken, Content-Type")
        response.headers.add("Access-Control-Allow-Credentials", "true")
        return response

    # GPT 질문 생성 엔드포인트
    @app.route('/generate-question', methods=['POST', 'OPTIONS'])
    @token_required
    def generate_question(current_user=None):
        """
        전입신고서 작성 질문 생성
        """
        if request.method == "OPTIONS":
            return set_cors_headers(jsonify({"status": "OK"})), 200
        elif request.method == "POST":
            data = request.json
            document_type = data.get("documentType", "전입신고서")
            questions = generate_questions(document_type)
            return jsonify({"success": True, "questions": questions})

    # 값 삽입 및 문서 생성 엔드포인트
    @app.route('/submit-response', methods=['POST', 'OPTIONS'])
    @token_required
    def submit_response(current_user=None):
        """
        사용자 응답  처리:
        - CSV 파일 생성
        - DOCUMENT 및 DOC_FILE 저장
        """
        if request.method == "OPTIONS":
            return set_cors_headers(jsonify({"status": "OK"})), 200
        elif request.method == "POST":
            try:
                data = request.json
                log.info(f"요청 데이터 수신: {data}")

                responses = data.get("values", {})
                document_type=data.get("documentType", "document")

                if not responses or not document_type:
                    return jsonify({"success": False, "message": "입력 데이터가 유효하지 않습니다."}), 400


                # CSV 생성 및 데이터 저장
                result=generate_csv_and_upload(responses, document_type)

                if not result:
                    return jsonify({"success": False, "message": "CSV 생성 또는 데이터 저장 실패"}), 500

                return jsonify({
                    "success": True,
                    "message": "CSV 파일 생성 및 데이터 저장 성공",
                    "documentId": result["documentId"],
                    "csvPath": result["csvPath"]
                })

            except Exception as e:
                log.error(f"문서 처리 중 오류 발생: {e}")
                return jsonify({"success": False, "message": "문서 처리 중 오류 발생"}), 500

    # 문서 다운로드 엔드포인트
    @app.route('/download-document', methods=['GET', 'OPTIONS'])
    @token_required
    def download_document(current_user=None):
        """
        CSV 파일 다운로드
        """
        if request.method == "OPTIONS":
            return set_cors_headers(jsonify({"status": "OK"})), 200
        elif request.method == "GET":
            file_path = request.args.get('file_path')  # 쿼리 매개변수로 파일 경로 받기 ("processed/address.csv")

            if not file_path or not os.path.exists(file_path):
                return jsonify({"success": False, "message": "파일을 찾을 수 없습니다."}), 404

            # CSV 파일의 MIME type과 파일 이름 명시
            return send_file(
                file_path,
                as_attachment=True,
                mimetype='text/csv; charset=utf-8',
                download_name=os.path.basename(file_path)  # Flask >= 2.0
            )
