import base64
import math
from io import BytesIO
import cv2
import mediapipe as mp
import numpy as np
from PIL import Image
from flask import request, jsonify, Flask
import dbConnectTemplate as dbtemp
import uuid
from datetime import datetime
import pytz
import os

from twilio.rest import Client

account_sid = os.getenv("ACCOUNT_SID")
auth_token = os.getenv("AUTH_TOKEN")
client = Client(account_sid, auth_token)


# 전역 변수
COORDINATE_SIZE = 33  # 저장(X, Y) 배열사이즈
MOVE_DISTANCE = 0.35  # 움직인 거리
EMG_PROB = 0.35 # 정확도

mp_holistic = mp.solutions.holistic
holistic = mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5)

previous_X = np.zeros(COORDINATE_SIZE)  # 이전 X 좌표 배열
previous_Y = np.zeros(COORDINATE_SIZE)  # 이전 Y 좌표 배열
array_EMG = []

dbtemp.oracle_init()

def register_routes(app) :
    @app.route('/emg/start', methods=['POST'])
    def emg_start():
        data = request.get_json()
        image_data_list = data.get('images', [])
        memUUID = data.get('uuid')
        sessId = data.get('sessId')
        print("memUUID : " + memUUID)
        print("sessId : " + sessId)

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

            isEMG = True
            # 감지된 포즈의 랜드마크 그리기
            if result.pose_landmarks:

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

            array_EMG.append(isEMG)

        # 리소스 해제

        cv2.destroyAllWindows()
        print(array_EMG)
        isEMG, emgUUID = probabilityEMG(array_EMG, memUUID, sessId)

        return jsonify({"emgMSG": isEMG, "emgUUID": emgUUID}), 200

    @app.route('/emg/end', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
    def emg_end():
        global previous_X, previous_Y, array_EMG
        previous_X = np.zeros(COORDINATE_SIZE)  # 이전 X 좌표 배열
        previous_Y = np.zeros(COORDINATE_SIZE)  # 이전 Y 좌표 배열
        array_EMG = []
        print("초기화 완료")

        return jsonify("초기화 완료."), 200

    @app.route('/emg/cancel', methods=['POST'])
    def emg_cancel():
        data = request.get_json()
        memUUID = data.get('uuid')
        updateEMG(memUUID)
        return jsonify("업데이트 완료."), 200


def calculate_distance(x1, y1, x2, y2):
    # 유클리드 거리 계산
    distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    return distance

def probabilityEMG(array, memUUID, sessId):
    """
    motion_history 배열을 받아 True와 False의 비율을 계산하여 출력하는 함수
    """
    true_count = array.count(True)
    false_count = array.count(False)
    total = len(array)

    print(f'array: {array}')
    print(f'memUUID: {memUUID}')
    print(f'sessId: {sessId}')

    if total > 0:
        true_ratio = true_count / total
        false_ratio = false_count / total
        print(f"True 비율: {true_ratio * 100:.2f}%")
        print(f"False 비율: {false_ratio * 100:.2f}%")
        print(f"False Count : {true_count}")
        if true_ratio >= EMG_PROB:
            emgUUID = insertEMG(memUUID, sessId)
            print("위급 상황입니다.")
            return "emg", emgUUID
        else:
            print("정상입니다.")
            return "normal", None
    else:
        print("모션 기록이 없습니다.")
def insertEMG(memUUID, sessId):

    EMG_LOG_ID = str(uuid.uuid4())
    EMG_CAP_PATH = None
    EMG_DETECTED_MOTION = "움직임 없음"
    EMG_ALERT_SENT_TO = ""
    EMG_CREATED_AT = None
    EMG_USER_UUID = memUUID
    EMG_CANCEL = "N"
    EMG_CANCLE_AT = None
    EMG_F_PHONE = "01052928302"
    EMG_S_PHONE = "01052928302"
    EMG_SESS_ID = sessId

    # KST (Korea Standard Time) 시간대 객체 생성
    kst = pytz.timezone('Asia/Seoul')
    # 현재 KST 시간 가져오기
    EMG_CREATED_AT = datetime.now(kst)

    query = f"select * from member WHERE MEM_UUID = '{memUUID}'"
    conn = dbtemp.connect()
    cursor = conn.cursor()  # db 연결 정보로 커서 객체를 생성함

    try:
        cursor.execute(query)  # 쿼리문을 db로 전송하고 실행한 결과를 커서가 받음

        # 컬럼명 얻기
        columns = [desc[0] for desc in cursor.description]

        rows = cursor.fetchall()
        for row in rows:
            EMG_ALERT_SENT_TO = row[columns.index("MEM_UUID_MGR")]
            print(f"EMG_ALERT_SENT_TO: {EMG_ALERT_SENT_TO}")

        tp_value = (EMG_LOG_ID, EMG_CAP_PATH, EMG_DETECTED_MOTION, EMG_ALERT_SENT_TO, EMG_CREATED_AT,
                    EMG_USER_UUID, EMG_CANCEL, EMG_CANCLE_AT, EMG_F_PHONE, EMG_S_PHONE, EMG_SESS_ID)
        print(tp_value)
        query = "insert into EMERGENCY_LOG values (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11)"

        cursor.execute(query, tp_value)
        dbtemp.commit(conn)
        print("commit")
    except Exception as e:
        dbtemp.rollback(conn)
        EMG_LOG_ID = None
        print(f"rollback error: {e}")
    finally:
        cursor.close()
        conn.close()

        return EMG_LOG_ID

def updateEMG(uuid):
    print(uuid)

    # KST (Korea Standard Time) 시간대 객체 생성
    kst = pytz.timezone('Asia/Seoul')
    # 현재 KST 시간 가져오기
    EMG_CANCLE_AT = datetime.now(kst)

    conn = dbtemp.connect()
    cursor = conn.cursor()  # db 연결 정보로 커서 객체를 생성함
    query = f"update emergency_log set EMG_CANCEL = :1, EMG_CANCLE_AT = :2 where EMG_LOG_ID = :3"
    tp_value = ("Y", EMG_CANCLE_AT, uuid)
    try:
        cursor.execute(query,tp_value)  # 쿼리문을 db로 전송하고 실행한 결과를 커서가 받음
        print(cursor.fetchall)
        dbtemp.commit(conn)
        # make_call()
    except Exception as e:
        dbtemp.rollback(conn)
        print(f"rollback error: {e}")
    finally:
        cursor.close()
        conn.close()


def make_call():
    call = client.calls.create(
        twiml="<Response><Say>The current guardian is in danger</Say></Response>",
        to="+821052928302",
        from_="+12298087476",
    )

    messages = client.messages.create(
        to="+821052928302",
        from_="+12298087476",
        body="위급 상황입니다."
    )