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

        # 인증 실패 알림 예약 (정각 기준)
        key = f"{user.id}-{tag}"
        scheduler.add_job(check_and_alert, DateTrigger(run_date=target_time), args=[user, channel, key])

        # 타임스탬프 기록
        pending = load_json("pending_check.json")
        pending[key] = alarm_time.strftime("%Y-%m-%d %H:%M:%S")
        save_json("pending_check.json", pending)

    except Exception as e:
        print(f"[ERROR] 인증 예약 실패: {e}")

def load_json(file):
    return json.load(open(file, encoding="utf-8")) if os.path.exists(file) else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

@bot.command()
async def 인증(ctx, item: str):
    item = item.lower()
    uid = str(ctx.author.id)

    if item not in ALLOWED_ITEMS:
        return await ctx.send("❌ 올바른 항목: planner, lunch, dinner, checkout")
    
    if not ctx.message.attachments:
        return await ctx.send("❌ 사진을 함께 첨부해주세요.")
    
    img_bytes = await ctx.message.attachments[0].read()
    now = datetime.now(KST)

    # 📌 플래너 인증
    if item == "planner":
        if not (now.hour == 8 or (now.hour == 9 and now.minute == 0)):
            return await ctx.send("❌ 플래너 인증은 **오전 8시 ~ 9시 정각까지만** 가능합니다.")

        result = await analyze_image_and_feedback(img_bytes)
        if "error" in result:
            return await ctx.send(f"❌ GPT 분석 실패: {result['error']}")

        save_submission(uid)
        add_payback(uid, item)
        schedule_auth(ctx.author, ctx.channel, "점심 전", result["lunch"])
        schedule_auth(ctx.author, ctx.channel, "저녁 전", result["dinner"])
        schedule_auth(ctx.author, ctx.channel, "공부 종료 전", result["end"])
        return await ctx.send(f"✅ 플래너 제출 완료 + 페이백 적용!\n📊 분석결과: {result}")

    # 📌 그 외(lunch/dinner/checkout) 인증
    if item in ["lunch", "dinner", "checkout"]:
        tag_map = {
            "lunch": "점심 전",
            "dinner": "저녁 전",
            "checkout": "공부 종료 전"
        }
        tag = tag_map[item]
        key = f"{uid}-{tag}"

        # 인증 성공 기록 (사진만 있으면 성공으로 간주)
        verified = load_json("verified_users.json")
        today = datetime.now(KST).strftime("%Y-%m-%d")
        if today not in verified:
            verified[today] = {}
        verified[today][key] = True
        save_json("verified_users.json", verified)

        # 시간 초과 확인
        pending = load_json("pending_check.json")
        if key in pending:
            expire_time = datetime.strptime(pending[key], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST) + timedelta(minutes=2)
            if datetime.now(KST) > expire_time:
                return await ctx.send(f"⏰ `{item}` 인증 시간이 지났습니다. 페이백이 적용되지 않습니다.")

        save_submission(uid)
        add_payback(uid, item)
        return await ctx.send(f"✅ `{item}` 인증 완료 + 페이백 적용!")

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    await bot.process_commands(msg)

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))
