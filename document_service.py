import csv

import openai
from docx import Document
import os
from flask import request, jsonify, send_file
from common_utils import token_required, log  # 공통 코드에서 가져옴
import json

# NAS 공유 폴더 접근
FTP_SERVER = "ktj0514.synology.me"
FTP_PORT = 21
FTP_USERNAME = "anonymous"
FTP_PASSWORD = "anonymous@"
FTP_REMOTE_DIR = "files/document"

# 템플릿 및 처리된 파일 경로 생성
os.makedirs("processed", exist_ok=True)


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

    def create_csv_from_responses(responses, output_path):
        """
        사용자 응답을 기반으로 CSV 파일 생성 (BOM 추가)
        """
        try:
            with open(output_path, mode='w', newline='', encoding='utf-8-sig') as csv_file:
                writer =csv.writer(csv_file)
                writer.writerow(["Key", "Value"])  # 헤더 추가
                for key, value in responses.items():
                    writer.writerow([key, value])
            log.info(f"CSV 파일 생성 완료: {output_path}")
            return output_path
        except Exception as e:
            log.error(f"CSV 파일 생성 중 오류: {e}")
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
        사용자 응답을 받아 문서 생성
        """
        if request.method == "OPTIONS":
            return set_cors_headers(jsonify({"status": "OK"})), 200
        elif request.method == "POST":
            data = request.json
            log.info(f"Received data: {data}")

            responses = data.get("values", {})
            if not responses:
                return jsonify({"success": False, "message": "Values are missing"}), 400

            document_type = data.get("documentType", "document")

            if not responses:
                return jsonify({"success": False, "message": "Responses are missing"}), 400

            csv_path = f"processed/{document_type}.csv"
            create_csv_from_responses(responses, csv_path)

            if not os.path.exists(csv_path):
                return jsonify({"success": False, "message": "File creation failed"}), 500

            return jsonify({"success": True, "csv_path": csv_path})

    # 문서 다운로드 엔드포인트
    @app.route('/download-document', methods=['GET', 'OPTIONS'])
    @token_required
    def download_document(current_user=None):
        """
        생성된 파일을 다운로드
        """
        if request.method == "OPTIONS":
            return set_cors_headers(jsonify({"status": "OK"})), 200
        elif request.method == "GET":
            file_path = request.args.get('file_path') # 쿼리 매개변수로 파일 경로 받기 ("processed/address.csv")

            if not file_path or not os.path.exists(file_path):
                return jsonify({"success": False, "message": "File not found"}), 404

            # CSV 파일의 MIME type과 파일 이름 명시
            return send_file(
                file_path,
                as_attachment=True,
                mimetype='text/csv; charset=utf-8',
                download_name=os.path.basename(file_path)  # Flask >= 2.0
            )
