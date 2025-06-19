# ✅ ocr_analyzer.py
from PIL import Image
import pytesseract
import io
import base64
import json
import openai
import os
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def convert_image_to_base64(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"❌ Base64 변환 실패: {e}")
        return None

async def analyze_image_and_feedback(image_bytes):
    try:
        b64 = convert_image_to_base64(image_bytes)
        if not b64:
            return {"error": "이미지를 base64로 변환하는 데 실패했습니다."}

        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "다음은 공부 플래너 사진입니다. 각 항목을 다음 3가지 중 하나로 분류하세요:\n"
                               "(1) 시간 과목 분량\n(2) 시간 (점심/저녁)\n(3) 시간 (기타 일정)\n"
                               "그 중 점심/저녁/마지막 공부 종료 시간만 추려서 아래 형식으로 JSON 출력:\n"
                               "{\"lunch\":\"13:00\", \"dinner\":\"18:00\", \"end\":\"22:00\"}"
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )

        print("🔥 GPT 응답 전체:", response)

        content = response["choices"][0]["message"].get("content", "").strip()
        print("📄 GPT content:", content)

        if not content:
            return {"error": "GPT 응답이 비어 있습니다."}

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"error": f"GPT 응답이 JSON 형식이 아닙니다:\n{content}"}

    except Exception as e:
        return {"error": f"GPT 호출 실패: {e}"}
