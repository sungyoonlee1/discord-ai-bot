import openai
import base64
import json
import os
import re

from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def convert_image_to_base64(image_bytes):
    try:
        image = Image.open(BytesIO(image_bytes))
        buffered = BytesIO()
        image.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception:
        return None

def extract_json(text):
    match = re.search(r'\{.*?\}', text, re.DOTALL)
    if match:
        return match.group()
    return None

async def analyze_image_and_feedback(image_bytes):
    b64 = convert_image_to_base64(image_bytes)
    if not b64:
        return {"error": "이미지를 base64로 변환하는 데 실패했습니다."}

    try:
        response = await openai.ChatCompletion.acreate(  # ✅ 비동기 버전으로 변경
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "다음은 공부 플래너 사진입니다. 각 항목을 다음 3가지 중 하나로 분류하세요:\n"
                               "(1) 시간 과목 분량\n"
                               "(2) 시간 (점심/저녁)\n"
                               "(3) 시간 (기타 일정)\n"
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

        content = response.choices[0].message.content.strip()
        print("🧠 GPT 응답:", content)

        if not content:
            return {"error": "GPT 응답이 비어 있습니다."}

        json_text = extract_json(content)
        if not json_text:
            return {"error": f"응답에서 JSON을 찾을 수 없습니다:\n{content}"}

        return json.loads(json_text)

    except Exception as e:
        return {"error": str(e)}
