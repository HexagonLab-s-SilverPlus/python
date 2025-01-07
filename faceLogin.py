from flask import Flask, request, jsonify
from flask_cors import CORS
from deepface import DeepFace
import cv2
import numpy as np
import base64
from io import BytesIO
import tempfile
import os
import ftp_utility as ftp

app = Flask(__name__)
CORS(app)  # 모든 도메인에서 요청 허용

# FTP 설정
FTP_SERVER = "ktj0514.synology.me"
FTP_PORT = 21
FTP_USERNAME = "anonymous"
FTP_PASSWORD = ""
FTP_REMOTE_DIR = "/files/member/profile"

def fetch_all_images_from_ftp():
    ftputility = ftp.FTPUtility(FTP_SERVER, FTP_PORT, FTP_USERNAME, FTP_PASSWORD)
    try:
        ftputility.connect()
        file_list = ftputility.list_files(FTP_REMOTE_DIR)
        images = []
        for file_name in file_list:
            try:
                corrected_path = f"{FTP_REMOTE_DIR}/{file_name}"
                image_file = ftputility.open_file(corrected_path)
                file_bytes = np.asarray(bytearray(image_file.read()), dtype=np.uint8)
                img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
                images.append((file_name, img))
            except Exception as e:
                print(f"Error fetching file {file_name}: {e}")
                continue
        return images
    except Exception as e:
        print(f"Error fetching images from FTP: {e}")
        return []
    finally:
        ftputility.disconnect()

def compare_face_with_all_profiles(camera_frame, profile_images, threshold_override=0.40):
    best_match = None
    best_distance = float('inf')
    for file_name, profile_img in profile_images:
        try:
            temp_camera_path = save_temp_image(camera_frame)
            temp_profile_path = save_temp_image(profile_img)
            result = DeepFace.verify(
                img1_path=temp_camera_path,
                img2_path=temp_profile_path,
                detector_backend='retinaface',
                model_name='ArcFace'
            )
            distance = result['distance']
            threshold = threshold_override

            # 로그 출력 추가
            print(f"Comparing with {file_name}: Distance = {distance}, Threshold = {threshold}")

            if distance < threshold and distance < best_distance:
                best_match = (file_name, distance)
                best_distance = distance
            delete_temp_file(temp_camera_path)
            delete_temp_file(temp_profile_path)
        except Exception as e:
            print(f"Error comparing with {file_name}: {e}")
            continue

    # 0.4 이하인 경우만 반환
    if best_match and best_distance <= threshold_override:
        return best_match
    return None

def save_temp_image(img):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    temp_file_path = temp_file.name
    cv2.imwrite(temp_file_path, img)
    return temp_file_path

def delete_temp_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)

@app.route("/compare", methods=["POST"])
def compare_faces():
    try:
        data = request.json
        image_data = data.get("image")
        if not image_data:
            return jsonify({"error": "No image data provided"}), 400
        image_bytes = base64.b64decode(image_data.split(",")[1])
        np_array = np.frombuffer(image_bytes, np.uint8)
        camera_frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
        profile_images = fetch_all_images_from_ftp()
        if not profile_images:
            return jsonify({"error": "No profile images found on NAS"}), 404
        best_match = compare_face_with_all_profiles(camera_frame, profile_images)
        if best_match:
            file_name, distance = best_match
            return jsonify({"best_match": file_name, "distance": distance, "status": "success"})
        else:
            return jsonify({"best_match": None, "distance": None, "status": "no_match"})
    except Exception as e:
        print(f"Error during comparison: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
