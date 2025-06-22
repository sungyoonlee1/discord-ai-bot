# ✅ main.py
공지사항채널ID = 1381470992551120982
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
            return  # 과거는 무시

        # 인증 요청 예약
        scheduler.add_job(send_auth, DateTrigger(run_date=alarm_time), args=[user, channel, tag])

        # 인증 실패 알림 예약
        key = f"{user.id}-{tag}"
        scheduler.add_job(check_and_alert, DateTrigger(run_date=target_time), args=[user, channel, key])

        # 타임스탬프 기록
        pending = load_json("pending_check.json")
        pending[key] = alarm_time.strftime("%Y-%m-%d %H:%M:%S")
        save_json("pending_check.json", pending)

        # ✅ 추가: 인증 시간대에만 on 모드 설정
        mode_map = {
            "점심 전": "lunch",
            "저녁 전": "dinner",
            "공부 종료 전": "checkout"
        }
        if tag in mode_map:
            schedule_mode_switch(user.id, mode_map[tag], time_str)

    except Exception as e:
        print(f"[ERROR] 인증 예약 실패: {e}")  # ← 이 줄이 반드시 필요해!

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
    print(f"✅ Logged in as {bot.user}")
    scheduler.add_job(check_missed, "cron", hour=9, minute=0, timezone=KST)
    scheduler.add_job(send_announcement, "cron", hour=8, minute=0, timezone=KST,
                      args=[공지사항채널ID, "📢 플래너 인증 시간입니다! 오전 9시까지 제출해 주세요."])
    scheduler.add_job(reset_all_user_modes, "cron", hour=8, minute=0, timezone=KST)
    scheduler.add_job(send_announcement, "cron", hour=9, minute=0, timezone=KST,
                      args=[공지사항채널ID, "⛔ 오전 9시 마감! 이제 제출해도 페이백은 불가합니다."])
    scheduler.start()

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
        data[uid]["last_updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    save_user_state(data)

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return

    now = datetime.now(KST)

    # 1️⃣ 00시 ~ 08시: 사진 무시
    if now.hour < 8:
        return

    # 2️⃣ 사진만 보냈는지 확인
    if not msg.attachments or msg.content.strip():
        return

    uid = str(msg.author.id)
    state = load_user_state().get(uid, {})
    mode = state.get("current_mode", "off")
    submitted = state.get("planner_submitted", False)

    # 3️⃣ 플래너 자동 분석 (모드가 on이고 아직 제출 안 됐을 때)
    if mode == "on" and not submitted:
        img_bytes = await msg.attachments[0].read()
        result = await analyze_image_and_feedback(img_bytes)

        if "error" in result:
            return await msg.channel.send(f"❌ GPT 분석 실패: {result['error']}")

        update_user_state(uid, current_mode="off", planner_submitted=True)
        save_submission(uid)
        add_payback(uid, "planner")

        schedule_auth(msg.author, msg.channel, "점심 전", result["lunch"])
        schedule_auth(msg.author, msg.channel, "저녁 전", result["dinner"])
        schedule_auth(msg.author, msg.channel, "공부 종료 전", result["end"])

        return await msg.channel.send(
            f"✅ 플래너 제출 완료 + 페이백 적용!\n📊 분석결과: {result}"
        )

    # 4️⃣ 인증 시간대 응답 (lunch/dinner/checkout)
    if mode not in ["lunch", "dinner", "checkout"]:
        return

    if not submitted:
        return  # 플래너 제출 안 했으면 무시

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
            return await msg.channel.send(f"⏰ `{mode}` 인증 시간이 지났습니다. 페이백이 적용되지 않습니다.")

    save_submission(uid)
    add_payback(uid, mode)
    return await msg.channel.send(f"✅ `{mode}` 인증 완료 + 페이백 적용!")

    # 5️⃣ 명령어 처리
    await bot.process_commands(msg)

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))
