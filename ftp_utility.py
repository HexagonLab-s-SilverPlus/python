from ftplib import FTP

class FTPUtility:
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
        print(f"원본 파일 목록: {files}")
        decoded_files = [f.encode('latin-1').decode('utf-8', 'ignore') for f in files]
        print(f"디코딩된 파일 목록: {decoded_files}")
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

    def dissconnect(self):
        if self.ftp:
            self.ftp.quit()
            print("Disconnect from FTP server")
