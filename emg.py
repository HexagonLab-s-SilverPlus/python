import base64
import math
from io import BytesIO
import cv2
import mediapipe as mp
import numpy as np
from PIL import Image
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request, jsonify, Flask
import time

# 전역 변수
TIME_LIMIT = 20  # 카메라 켜지는 시간
CHECK_TIME = 0.1  # 모션트래킹 측정할 시간 간격
COORDINATE_SIZE = 33  # 저장(X, Y) 배열사이즈
MOVE_DISTANCE = 0.35  # 움직인 거리

mp_holistic = mp.solutions.holistic
holistic = mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5)

previous_X = np.zeros(COORDINATE_SIZE)  # 이전 X 좌표 배열
previous_Y = np.zeros(COORDINATE_SIZE)  # 이전 Y 좌표 배열
array_EMG = []

def register_routes(app) :
    @app.route('/emg/start', methods=['POST'])
    def start_emg_test():
        print(array_EMG)
        data = request.get_json()
        image_data_list = data.get('images', [])

        if not image_data_list:
            return jsonify({'message': '이미지가 제공되지 않았습니다.'}), 400

        # Base64로 전달된 이미지를 디코딩하여 처리
        images = []
        for image_data in image_data_list:
            if image_data:
                # Base64로 전달된 이미지를 디코딩하여 처리
                image_data = base64.b64decode(image_data.split(',')[1])  # 'data:image/jpeg;base64,' 제거
                image = Image.open(BytesIO(image_data))
                image = np.array(image)  # 이미지 배열로 변환
                images.append(image)
            else:
                return jsonify({'message': '잘못된 이미지 형식입니다.'}), 40
            # 이미지를 RGB로 변환

            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            # Holistic 모델 사용하여 랜드마크 추출
            result = holistic.process(rgb_image)

            # 감지된 포즈의 랜드마크 그리기
            if result.pose_landmarks:

                isEMG = True
                for i in range(len(result.pose_landmarks.landmark)):
                    landmark = result.pose_landmarks.landmark[i]

                    # 랜드마크 좌표를 화면에 그리기
                    h, w, _ = image.shape
                    cx, cy = int(landmark.x * w), int(landmark.y * h)
                    cv2.circle(image, (cx, cy), 5, (0, 255, 0), -1)  # 초록색 점으로 표시

                    distance = calculate_distance(landmark.x, landmark.y, previous_X[i], previous_Y[i])


                    if distance > MOVE_DISTANCE:
                        previous_X[i], previous_Y[i] = landmark.x, landmark.y
                        isEMG = False
                    else:
                        previous_X[i], previous_Y[i] = landmark.x, landmark.y

            array_EMG.append(isEMG)
            print(isEMG)

        # 리소스 해제

        cv2.destroyAllWindows()
        print(array_EMG)
        probabilityEMG(array_EMG)

        return jsonify("message EMG 테스트."), 200

    @app.route('/emg/end', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
    def end_emg_test():
        global previous_X, previous_Y, array_EMG
        previous_X = np.zeros(COORDINATE_SIZE)  # 이전 X 좌표 배열
        previous_Y = np.zeros(COORDINATE_SIZE)  # 이전 Y 좌표 배열
        array_EMG = []
        print("초기화 완료")

        return jsonify("초기화 완료."), 200

# def register_routes(app):
#     @app.route("/emg/start", methods=["POST"])
#     def start_webcam():
#         cap = cv2.VideoCapture(0)
#         start_Time, previous_time = time.time(),time.time()
#         isInit = False
#         isEMG = False
#
#         previous_X = np.zeros(COORDINATE_SIZE)  # 이전 X 좌표 배열
#         previous_Y = np.zeros(COORDINATE_SIZE)  # 이전 Y 좌표 배열
#
#         array_EMG = []
#
#         while cap.isOpened():
#             ret, frame = cap.read()
#             if not ret:
#                 print("웹캠을 열 수 없습니다.")
#                 break
#             current_time = time.time()
#
#             # BGR 이미지를 RGB로 변환
#             rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
#
#             # Holistic 모델 사용
#             result = holistic.process(rgb_frame)
#
#             # 감지된 포즈의 랜드마크 그리기
#             if result.pose_landmarks:
#
#                 isEMG = True
#                 for i in range(len(result.pose_landmarks.landmark)):
#                     landmark = result.pose_landmarks.landmark[i]
#
#                     # 랜드마크 좌표를 화면에 그리기
#                     h, w, _ = frame.shape
#                     cx, cy = int(landmark.x * w), int(landmark.y * h)
#                     cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)  # 초록색 점으로 표시
#
#                     if current_time - previous_time > CHECK_TIME:
#                         distance = calculate_distance(landmark.x,  landmark.y, previous_X[i], previous_Y[i])
#
#                         if isInit:
#                             if distance > MOVE_DISTANCE:
#                                 previous_X[i], previous_Y[i] = landmark.x, landmark.y
#                                 isEMG = False
#                                 break
#                         else:
#                             previous_X[i], previous_Y[i] = landmark.x,  landmark.y
#
#                         if i == len(result.pose_landmarks.landmark) - 1:
#                             isInit = True
#
#             if current_time - previous_time > CHECK_TIME:
#                 array_EMG.append(isEMG)
#                 previous_time = current_time
#                 print(isEMG)
#
#
#             # 결과 화면에 표시
#             cv2.imshow("Pose Detection", frame)
#
#             # 'q'를 눌러 종료
#             if isTimeOver(start_Time):
#                 break
#             if cv2.waitKey(1) & 0xFF == ord('q'):
#                 break
#
#         # 리소스 해제
#         cap.release()
#         cv2.destroyAllWindows()
#         print(array_EMG)
#         probabilityEMG(array_EMG)
#
#         return jsonify({"message": "EMG 테스트."}), 200

def isTimeOver(start_Time):
    if  time.time() - start_Time > TIME_LIMIT:
        return True
    else:
        return False

def calculate_distance(x1, y1, x2, y2):
    # 유클리드 거리 계산
    distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    return distance

def probabilityEMG(array):
    """
    motion_history 배열을 받아 True와 False의 비율을 계산하여 출력하는 함수
    """
    true_count = array.count(True)
    false_count = array.count(False)
    total = len(array)

    if total > 0:
        true_ratio = true_count / total
        false_ratio = false_count / total
        print(f"True 비율: {true_ratio * 100:.2f}%")
        print(f"False 비율: {false_ratio * 100:.2f}%")
    else:
        print("모션 기록이 없습니다.")

# 웹캠 시작
# start_webcam()