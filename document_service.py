import openai
from docx import Document
import subprocess
import os
from flask import request, jsonify, send_file
from common_utils import token_required, log  # 공통 코드에서 가져옴
import re

# 프로젝트 루트 경로
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 템플릿 및 처리된 파일 경로 생성
os.makedirs("templates", exist_ok=True)
os.makedirs("processed", exist_ok=True)

def register_routes(app):
    # .docx에서 키 추출
    def extract_keys_from_docx(template_path):
        """
        .docx 파일에서 키(예: {이름}, {주소})를 자동으로 추출
        """
        try:
            doc = Document(template_path)
            keys = set()
            for para in doc.paragraphs:
                print(f"문단 내용: {para.text}")  # 텍스트 디버깅
                matches = re.findall(r"\{(.*?)}", para.text)
                keys.update(matches)

            return list(keys)
        except Exception as e:
            print(f".docx 파일 키 추출 중 오류 발생: {e}")
            return []

    # 문서 선택 엔드포인트
    @app.route('/select-document', methods=['POST'])
    @token_required
    def select_document():
        """
        사용자가 선택한 문서에 따라 키 값 추출
        """
        data = request.json
        document_type = data.get('documentType')  # 예: "전입신고서"

        # templates 폴더 경로
        TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

        documents = {
            "전입신고서": os.path.join(TEMPLATES_DIR, '전입신고서.docx'),
            "사망신고서": os.path.join(TEMPLATES_DIR, '전입신고서.docx'),
            "의료급여 신청서": os.path.join(TEMPLATES_DIR, '전입신고서.docx'),
            "기초연금 신청서": os.path.join(TEMPLATES_DIR, '전입신고서.docx')
        }
        template_path = documents.get(document_type)
        if not template_path:
            return jsonify({'success': False, 'message': 'Invalid document type'}), 400

        try:
            keys = extract_keys_from_docx(template_path)
            return jsonify({'success': True, 'keys': keys})
        except Exception as e:
            log.error(f".docx 키 추출 실패: {e}")
            return jsonify({'success': False, 'message': 'Failed to extract keys from .docx'}), 500

    # GPT 질문 생성 엔드포인트
    @app.route('/generate-question', methods=['POST'])
    @token_required
    def generate_question():
        """키 값을 기반으로 GPT 질문 생성"""
        data = request.json
        key = data.get('key')  # 예: "이름"

        # GPT로 질문 생성
        prompt = f"{key}를 어르신에게 쉽게 여쭤봐주세요."
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "너는 어르신에게 친근하고 이해하기 쉽게 안내하는 AI 비서야."},
                {"role": "user", "content": prompt}
            ]
        )
        question = response.choices[0].message['content']
        return jsonify({'success': True, 'question': question})

    # .docx에 값 삽입
    def insert_values_to_docx(template_path, output_path, values):
        """
        .docx 파일에 값을 삽입
        """
        try:
            doc = Document(template_path)
            for para in doc.paragraphs:
                for key, value in values.items():
                    if f"{{{key}}}" in para.text:
                        para.text = para.text.replace(f"{{{key}}}", value)

            doc.save(output_path)
            print(f"문서 생성 완료: {output_path}")

            # 파일 크기 확인 및 빈 파일 처리
            if os.path.exists(output_path) and os.path.getsize(output_path) == 0:
                os.remove(output_path)
                raise Exception("생성된 파일이 비어 있습니다.")
        except Exception as e:
            print(f".docx 파일 처리 중 오류 발생: {e}")

    # 값 삽입 및 HWP 변환 엔드포인트
    @app.route('/submit-values', methods=['POST'])
    @token_required
    def submit_values():
        """
        사용자 입력 값으로 .docx 파일 생성 및 HWP 변환
        """
        data = request.json
        document_type = data.get('documentType')  # 예: "전입신고서"
        values = data.get('values')  # 예: {"이름": "홍길동", "주소": "서울시 강남구"}

        documents = {
            "전입신고서": "templates/전입신고서.docx",
            "사망신고서": "templates/사망신고서.docx",
            "의료급여 신청서": "templates/의료급여 신청서.docx",
            "기초연금 신청서": "templates/기초연금 신청서.docx"
        }
        template_path = documents.get(document_type)
        if not template_path:
            return jsonify({'success': False, 'message': 'Invalid document type'}), 400

        output_docx_path = f"processed/{document_type}_completed.docx"
        output_hwp_path = f"processed/{document_type}_completed.hwp"

        # .docx에 값 삽입
        try:
            insert_values_to_docx(template_path, output_docx_path, values)
        except Exception as e:
            return jsonify({'success': False, 'message': 'DOCX 파일 생성 실패', 'error': str(e)}), 500

        # .docx → .hwp 변환
        try:
            convert_docx_to_hwp(output_docx_path, "processed")

            # 변환된 HWP 파일이 비어 있는지 확인
            if os.path.exists(output_hwp_path) and os.path.getsize(output_hwp_path) == 0:
                os.remove(output_hwp_path)
                raise Exception("HWP 변환 파일이 비어 있습니다.")
        except Exception as e:
            return jsonify({'success': False, 'message': 'HWP 변환 실패', 'error': str(e)}), 500

        return jsonify({'success': True, 'file_path': output_hwp_path})

    # 문서 다운로드 엔드포인트
    @app.route('/download-document', methods=['GET'])
    def download_document():
        """
        생성된 문서를 다운로드
        """
        file_path = request.args.get('file_path')

        # 파일이 존재하지 않거나 빈 파일일 경우 처리
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return jsonify({'success': False, 'message': 'File not found or is empty'}), 404

        return send_file(file_path, as_attachment=True)

    # .docx → .hwp 변환 함수
    def convert_docx_to_hwp(docx_path, output_dir):
        """
        LibreOffice를 사용해 .docx를 .hwp로 변환
        """
        libreoffice_path = "C:\\Program Files\\LibreOffice\\program\\soffice.exe"
        try:
            result = subprocess.run(
                [libreoffice_path, "--headless", "--convert-to", "hwp", docx_path, "--outdir", output_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("STDOUT:", result.stdout.decode())
            print("STDERR:", result.stderr.decode())
            if result.returncode == 0:
                print(f"HWP 변환 성공: {output_dir}")
            else:
                print(f"LibreOffice 변환 실패: {result.stderr.decode()}")
                raise Exception("LibreOffice 변환 실패")
        except Exception as e:
            print(f"HWP 변환 중 오류 발생: {e}")
