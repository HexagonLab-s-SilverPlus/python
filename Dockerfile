FROM python:3.9

WORKDIR /app

# 최신 pip 설치
RUN pip install --upgrade pip

# 의존성 복사 및 설치
COPY clean_requirements.txt .
RUN pip install --no-cache-dir -r clean_requirements.txt

# 소스 코드 복사
COPY . .

# Flask 포트 노출
EXPOSE 5000

# 애플리케이션 실행
CMD ["python", "app.py"]
