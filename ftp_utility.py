from ftplib import FTP
import io

class FTPUtility:
    ftp = FTP()
    ftp.set_debuglevel(2)  # 디버깅 레벨 설정
    ftp.connect("ktj0514.synology.me", 21)
    ftp.login("anonymous", "")
    ftp.cwd("files/member/profile")
    ftp.retrlines("LIST")
    ftp.quit()

    def __init__(self, server, port, username, password):
        self.server = server
        self.port=port
        self.username=username
        self.password=password
        self.ftp=None

    def connect(self):
        self.ftp=FTP()
        self.ftp.connect(self.server, self.port)
        self.ftp.login(self.username, self.password)
        print(f"Connected to FTP server: {self.server}")

    def list_files(self, remote_dir):
        self.ftp.cwd(remote_dir)
        files = self.ftp.nlst()
        # 숨김 파일 필터링 및 디코딩
        decoded_files = [
            f.encode('latin-1').decode('utf-8', 'ignore') for f in files if not f.startswith("._")
        ]
        return decoded_files


    def download_file(self, remote_path, local_path):
        try:
            # 경로와 파일 이름 UTF-8 변환
            corrected_remote_path = remote_path.encode('utf-8').decode('latin-1')
            print(f"다운로드 경로: {corrected_remote_path}")

            with open(local_path, 'wb') as file:
                self.ftp.retrbinary(f'RETR {corrected_remote_path}', file.write) # 다운로드
            print(f"파일 다운로드 성공: {corrected_remote_path}")
        except UnicodeEncodeError as e:
            print(f"인코딩 오류 발생: {e}")
            raise
        except Exception as e:
            print(f"파일 다운로드 중 오류 발생: {e}")
            raise

    def disconnect(self):
        if self.ftp:
            self.ftp.quit()
            print("Disconnect from FTP server")

    def open_file(self, remote_path):
        """
        FTP에서 파일을 열어 데이터를 반환합니다.
        """
        try:
            print(f"Fetching file: {remote_path}")
            file_data = io.BytesIO()

            # 파일 다운로드
            self.ftp.retrbinary(f"RETR {remote_path}", file_data.write)
            file_data.seek(0)
            return file_data
        except Exception as e:
            print(f"Error while fetching file: {e}")
            raise
