# ✅ main.py
공지사항채널ID = 1381470992551120982
from flask import Flask
import uvicorn
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
import pytz
import os
import json
import asyncio
import random
from dotenv import load_dotenv
from ocr_analyzer import analyze_image_and_feedback

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not TOKEN:
    print("❌ DISCORD_BOT_TOKEN 환경변수 없음")
    exit(1)
if not OPENAI_API_KEY:
    print("❌ OPENAI_API_KEY 환경변수 없음")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler()

KST = pytz.timezone("Asia/Seoul")
SUBMIT_FILE = "submitted_users.json"
PAYBACK_FILE = "payback_records.json"
ALLOWED_ITEMS = ["planner", "lunch", "dinner", "checkout"]

def schedule_auth(user, channel, tag, time_str):
    try:
        target_time = datetime.strptime(time_str, "%H:%M").replace(
            year=datetime.now(KST).year,
            month=datetime.now(KST).month,
            day=datetime.now(KST).day,
            tzinfo=KST
        )
        alarm_time = target_time - timedelta(minutes=2)

        if alarm_time < datetime.now(KST):
            print(f"[SKIP] 이미 지난 인증 시간: {tag} ({alarm_time})")
            return

        scheduler.add_job(send_auth, DateTrigger(run_date=alarm_time), args=[user, channel, tag])

        key = f"{user.id}-{tag}"
        scheduler.add_job(check_and_alert, DateTrigger(run_date=target_time), args=[user, channel, key])

        pending = load_json("pending_check.json")
        pending[key] = alarm_time.strftime("%Y-%m-%d %H:%M:%S")
        save_json("pending_check.json", pending)

        mode_map = {
            "점심 전": "lunch",
            "저녁 전": "dinner",
            "공부 종료 전": "checkout"
        }
        if tag in mode_map:
            schedule_mode_switch(user.id, mode_map[tag], time_str)

        print(f"[예약 완료] {tag} 알람 등록 ({alarm_time}) → 모드: {mode_map.get(tag)}")

    except Exception as e:
        print(f"[ERROR] 인증 예약 실패 ({tag}): {e}")

# 여기서부터는 try 밖에서 정의
def set_user_mode(user_id, new_mode):
    update_user_state(user_id, current_mode=new_mode)

def reset_user_mode(user_id):
    update_user_state(user_id, current_mode="off")

def schedule_mode_switch(user_id, mode, time_str):
    try:
        target_time = datetime.strptime(time_str, "%H:%M").replace(
            year=datetime.now(KST).year,
            month=datetime.now(KST).month,
            day=datetime.now(KST).day,
            tzinfo=KST
        )
        scheduler.add_job(set_user_mode, DateTrigger(run_date=target_time - timedelta(minutes=2)), args=[user_id, mode])
        scheduler.add_job(reset_user_mode, DateTrigger(run_date=target_time + timedelta(minutes=2)), args=[user_id])
    except Exception as e:
        print(f"[ERROR] 모드 예약 실패: {e}")

def load_json(file):
    return json.load(open(file, encoding="utf-8")) if os.path.exists(file) else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

USER_STATE_FILE = "user_state.json"

def load_user_state():
    return load_json(USER_STATE_FILE)

def save_user_state(data):
    save_json(USER_STATE_FILE, data)

def update_user_state(user_id, **kwargs):
    uid = str(user_id)
    data = load_user_state()
    if uid not in data:
        data[uid] = {
            "planner_submitted": False,
            "lunch_time": None,
            "dinner_time": None,
            "end_time": None,
            "current_mode": "on",
            "last_updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        }
    for k, v in kwargs.items():
        data[uid][k] = v
    data[uid]["last_updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    save_user_state(data)
    
def save_submission(user_id):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    data = load_json(SUBMIT_FILE)
    if today not in data: data[today] = []
    if user_id not in data[today]:
        data[today].append(user_id)
    save_json(SUBMIT_FILE, data)

def add_payback(user_id, item):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    data = load_json(PAYBACK_FILE)
    if user_id not in data: data[user_id] = {}
    if today not in data[user_id]:
        data[user_id][today] = {"total": 0, "items": []}
    rec = data[user_id][today]
    if rec["total"] < 1000 and item not in rec["items"]:
        rec["items"].append(item)
        rec["total"] += 250
    save_json(PAYBACK_FILE, data)

async def send_announcement(channel_id, message):
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(message)

async def send_auth(user, channel, tag):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    submitted = load_json(SUBMIT_FILE).get(today, {})
    user_id = str(user.id)

    # 기본 메시지
    base_msg = f"{user.mention}님, 📸 **{tag} 인증 시간**입니다! 사진을 보내주세요."

    # planner 제출자라면 랜덤 범위 요청 추가
    if user_id in submitted:
        try:
            text = submitted[user_id]
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            chosen = random.choice(lines)
            base_msg += f"\n📝 추가 인증 요청: `{chosen}` 공부 인증 사진도 함께 보내주세요!"
        except Exception as e:
            print(f"[ERROR] 인증 범위 추출 실패: {e}")

    await channel.send(base_msg)

async def check_and_alert(user, channel, key):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    verified = load_json("verified_users.json")
    if verified.get(today, {}).get(key) != True:
        await channel.send(f"{user.mention}님, ⛔ `{key.split('-')[1]}` 인증을 2분 내에 완료하지 않았습니다. 페이백이 적용되지 않습니다.")

async def check_missed():
    await bot.wait_until_ready()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    submitted = load_json(SUBMIT_FILE).get(today, [])
    for g in bot.guilds:
        for m in g.members:
            if m.bot: continue
            if str(m.id) not in submitted:
                ch = discord.utils.get(g.text_channels, name=f"{m.name}-비서")
                if ch:
                    await ch.send(f"{m.mention}님, 오늘 오전 9시까지 플래너 미제출로 **페이백 제외** ❌")

@bot.event
async def on_ready():
    try:
        print(f"✅ Logged in as {bot.user}")

        print("🔁 사용자 모드 초기화 시작")
        reset_all_user_modes()
        print("✅ 사용자 모드 초기화 완료")

        print("📅 스케줄러 작업 추가 중...")

        scheduler.add_job(check_missed, "cron", hour=9, minute=0, timezone=KST)
        scheduler.add_job(send_announcement, "cron", hour=8, minute=0, timezone=KST,
                          args=[공지사항채널ID, "📢 플래너 인증 시간입니다! 오전 9시까지 제출해 주세요."])
        scheduler.add_job(reset_all_user_modes, "cron", hour=8, minute=0, timezone=KST)
        scheduler.add_job(send_announcement, "cron", hour=9, minute=0, timezone=KST,
                          args=[공지사항채널ID, "⛔ 오전 9시 마감! 이제 제출해도 페이백은 불가합니다."])

        scheduler.start()
        print("✅ 스케줄러 시작 완료")

    except Exception as e:
        print(f"[on_ready ERROR] {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    import traceback
    print(f"[on_error] event: {event}")
    traceback.print_exc()

@bot.event
async def on_member_join(member):
    guild = member.guild
    name = f"{member.name}-비서"
    cat = discord.utils.get(guild.categories, name="📁 학생비서")
    if not cat:
        cat = await guild.create_category("📁 학생비서")
    perms = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    ch = await guild.create_text_channel(name=name, category=cat, overwrites=perms)
    await ch.send(f"{member.mention}님, 전용 공부 비서 채널이 생성됐습니다.\n📸 **아침 9시 전까지 플래너를 제출**하면 페이백 대상이 됩니다!")

@bot.command()
async def 알림테스트(ctx):
    await send_announcement(ctx.channel.id, "🧪 테스트 알림입니다! 지금은 수동으로 호출한 메시지입니다.")

@bot.command()
async def 페이백(ctx):
    uid = str(ctx.author.id)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    data = load_json(PAYBACK_FILE).get(uid, {})
    amt = data.get(today, {}).get("total", 0)
    await ctx.send(f"💸 오늘 페이백: **{amt}원**")

def reset_all_user_modes():
    data = load_user_state()
    for uid in data:
        data[uid]["current_mode"] = "on"
        data[uid]["planner_submitted"] = False  # ✅ 매일 아침 플래너 제출 상태 초기화
        data[uid]["last_updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    save_user_state(data)

@bot.command()
async def 예약확인(ctx):
    now = datetime.now(KST)
    future = now + timedelta(hours=48)
    
    jobs = scheduler.get_jobs()
    upcoming = []

    for job in jobs:
        run_time = job.next_run_time
        if run_time and now <= run_time <= future:
            desc = f"- [{run_time.strftime('%Y-%m-%d %H:%M:%S')}] {job.name or '알 수 없음'}"
            upcoming.append(desc)
    
    if not upcoming:
        await ctx.send("⏰ 48시간 이내 예정된 알림이 없습니다.")
        return
    
    msg = "📅 앞으로 48시간 내 예정된 알림 목록:\n\n" + "\n".join(upcoming)
    await ctx.send(msg)

@bot.command()
async def 알람확인(ctx, user_id: str = None):
    if not user_id:
        return await ctx.send("❌ user_id를 입력해 주세요. 예: `!알람확인 1234567890`")
    
    state = load_user_state()
    user_info = state.get(user_id)
    
    if not user_info:
        return await ctx.send(f"❌ 해당 user_id `{user_id}` 정보를 찾을 수 없습니다.")
    
    reply = (
        f"📋 **유저 상태 정보 ({user_id})**\n"
        f"- 📌 current_mode: `{user_info.get('current_mode')}`\n"
        f"- ✅ planner_submitted: `{user_info.get('planner_submitted')}`\n"
        f"- 🍽 lunch_time: `{user_info.get('lunch_time' or '미지정')}`\n"
        f"- 🍱 dinner_time: `{user_info.get('dinner_time' or '미지정')}`\n"
        f"- 💤 end_time: `{user_info.get('end_time' or '미지정')}`\n"
        f"- ⏱ last_updated: `{user_info.get('last_updated')}`"
    )
    
    await ctx.send(reply)

@bot.command()
async def 상태초기화(ctx):
    update_user_state(str(ctx.author.id), current_mode="on", planner_submitted=False)
    await ctx.send("✅ 상태 초기화 완료! 다시 플래너 사진을 제출해주세요.")

@bot.event
async def on_message(msg):
    try:
        if msg.author.bot:
            return

        print(f"📩 메시지 감지: {msg.content}")
        print(f"📎 첨부파일 목록: {msg.attachments}")

        now = datetime.now(KST)

        # 1️⃣ 00시 ~ 08시: 사진 무시
        if now.hour < 8:
            await bot.process_commands(msg)
            return

        # 2️⃣ 사진이 없는 경우 명령어만 처리
        if not msg.attachments:
            await bot.process_commands(msg)
            return

        uid = str(msg.author.id)
        state = load_user_state().get(uid, {})
        mode = state.get("current_mode", "off")
        submitted = state.get("planner_submitted", False)

        print(f"🧾 상태 확인: mode = {mode}, submitted = {submitted}")  # 🔥 핵심 디버깅 줄

        # 3️⃣ 플래너 자동 분석
        if mode == "on" and not submitted:
            img_bytes = await msg.attachments[0].read()
            try:
                result = await analyze_image_and_feedback(img_bytes)
                print("분석 결과:", result)
                await msg.channel.send(f"[디버깅용] 분석결과: {result}")
            except Exception as e:
                import traceback
                print("🛑 분석 중 오류 발생")
                traceback.print_exc()
                await msg.channel.send(f"❌ GPT 분석 도중 오류 발생: {e}")
                return

            if not isinstance(result, dict):
                await msg.channel.send("❌ 분석 결과 형식이 잘못되어있습니다.")
                return

            if "error" in result:
                await msg.channel.send(f"❌ GPT 분석 실패: {result['error']}")
                return

            update_user_state(uid, current_mode="off", planner_submitted=True)
            save_submission(uid)
            add_payback(uid, "planner")

            print("🧪 현재 모드:", mode)
            print("🧪 제출 여부:", submitted)

            schedule_auth(msg.author, msg.channel, "점심 전", result["lunch"])
            schedule_auth(msg.author, msg.channel, "저녁 전", result["dinner"])
            schedule_auth(msg.author, msg.channel, "공부 종료 전", result["end"])

            await msg.channel.send(
                f"✅ 플래너 제출 완료 + 페이백 적용!\n📊 분석결과: {result}"
            )
            await bot.process_commands(msg)
            return

        # 4️⃣ 인증 응답
        if mode in ["lunch", "dinner", "checkout"] and submitted:
            mode_map = {
                "lunch": "점심 전",
                "dinner": "저녁 전",
                "checkout": "공부 종료 전"
            }
            tag = mode_map[mode]
            key = f"{uid}-{tag}"

            verified = load_json("verified_users.json")
            today = datetime.now(KST).strftime("%Y-%m-%d")
            if today not in verified:
                verified[today] = {}
            verified[today][key] = True
            save_json("verified_users.json", verified)

            pending = load_json("pending_check.json")
            if key in pending:
                expire_time = datetime.strptime(pending[key], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST) + timedelta(minutes=2)
                if datetime.now(KST) > expire_time:
                    await msg.channel.send(f"⏰ `{mode}` 인증 시간이 지났습니다. 페이백이 적용되지 않습니다.")
                    await bot.process_commands(msg)
                    return

            save_submission(uid)
            add_payback(uid, mode)
            await msg.channel.send(f"✅ `{mode}` 인증 완료 + 페이백 적용!")
            await bot.process_commands(msg)
            return

        # 5️⃣ 그 외에도 항상 명령어 인식되도록
        await bot.process_commands(msg)

    except Exception as e:
        import traceback
        print(f"🛑 on_message 예외 발생: {e}")
        traceback.print_exc()


# 📌 수정된 analyze_image_and_feedback 함수
from openai import AsyncOpenAI
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def analyze_image_and_feedback(image_bytes):
    print("\U0001f9ea analyze_image_and_feedback 호출됨")
    b64 = convert_image_to_base64(image_bytes)
    if not b64:
        return {"error": "이미지를 base64로 변환하는 데 실패했습니다."}

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "\ub2e4\uc74c\uc740 \uacf5\ubc31 \ud50c\ub798\ub108 \uc0ac\uc9c4\uc785\ub2c8\ub2e4. \uac01 \ud56d\ubaa9\uc744 \ub2e4\uc74c 3\uac00\uc9c0 \uc911 \ud558\ub098\ub85c \ubd84\ub958\ud558\uc138\uc694:\n(1) \uc2dc\uac04 \uacfc\ub150 \ubd84\ub7c9\n(2) \uc2dc\uac04 (\uc810\uc2ec/\uc800\ub141)\n(3) \uc2dc\uac04 (\uae30\ud0c0 \uc77c\uc815)\n\uadf8 \uc911 \uc810\uc2ec/\uc800\ub141/\ub9c8\uc9c0\ub9c9 \uacf5\ubc31 \uc885\ub8cc \uc2dc\uac04\ub9cc \ucd94\ub7b5\uc5d0\uc11c \uc544\ub798 \ud615\uc2dd\uc73c\ub85c JSON \ucd9c\ub825:\n{\"lunch\":\"13:00\", \"dinner\":\"18:00\", \"end\":\"22:00\"}"
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
        print("\U0001f9e0 GPT 응답:", content)

        if not content:
            return {"error": "GPT 응답이 비어 있습니다."}

        json_text = extract_json(content)
        if not json_text:
            return {"error": f"응답에서 JSON을 찾을 수 없습니다:\n{content}"}

        return json.loads(json_text)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def run_bot():
    bot.run(TOKEN)

if __name__ == "__main__":
    from flask import Flask
    from threading import Thread

    app = Flask('')

    @app.route('/')
    def home():
        return "I'm alive"

    def run():
        app.run(host='0.0.0.0', port=8080)

    Thread(target=run).start()

    import asyncio
    asyncio.run(bot.start(TOKEN))
