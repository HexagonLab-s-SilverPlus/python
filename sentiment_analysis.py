#https://huggingface.co/hun3359/klue-bert-base-sentiment

# Load model directly
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

tokenizer = AutoTokenizer.from_pretrained("hun3359/klue-bert-base-sentiment")
model = AutoModelForSequenceClassification.from_pretrained("hun3359/klue-bert-base-sentiment")

# 모델의 id2label 속성을 통해 감정 라벨을 가져옴
id2label = model.config.id2label

# id2label 확인
# print("id2label:", id2label)

def analyze_sentiment(text):
    """
    입력된 텍스트에 대해 감정 분석을 수행하고,
    가장 높은 확률을 가진 감정과 그 확률을 반환합니다.
    """
    # 입력 텍스트를 토큰화
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True)

    # 모델에 입력을 전달하여 예측 수행
    with torch.no_grad():
        outputs = model(**inputs)
    logits = outputs.logits

    # 소프트맥스 함수로 확률 계산
    probabilities = torch.softmax(logits, dim=1).squeeze()

    # 가장 높은 확률을 가진 감정의 인덱스와 확률 가져오기
    top_index = torch.argmax(probabilities).item()
    top_probability = probabilities[top_index].item()

    # 해당 인덱스의 감정 라벨 가져오기 (정수형 키 사용)
    top_emotion = id2label[top_index]

    # return top_emotion, top_probability
    return top_emotion

# 예제 문장 분석
# if __name__ == "__main__":
#     while True:
#         text = input("분석할 문장을 입력하세요 (종료하려면 'exit' 입력): ")
#         if text.lower() == "exit":
#             break
#         emotion, probability = analyze_sentiment(text)
#         print(f"입력 문장: {text}")
#         print(f"예측된 감정: {emotion}")
#         print(f"확률: {probability:.4f}")