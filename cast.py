# Powered by DeadlineTech
import sys
import platform
import os
import time
import asyncio
import psutil
from dotenv import load_dotenv
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError
from motor.motor_asyncio import AsyncIOMotorClient

# ==== ENV ====
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_DB_URI = os.getenv("MONGO_DB_URI")
LOGGER_GROUP_ID = -1002144355688

# ==== INIT ====
app = Client("BroadcastBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_DB_URI)
mongodb = mongo_client.deadline
usersdb = mongodb.tgusersdb
chatsdb = mongodb.chats
broadcast_logs = mongodb.broadcastlogs

START_TIME = time.time()

OWNER_ID = 7765692814
OWNER_ID2 = 6848223695
SECOND_OWNER_ID = 5350261891
ALLOWED_ADMINS = [OWNER_ID, SECOND_OWNER_ID, OWNER_ID2]
sudo_admin_filter = filters.user(ALLOWED_ADMINS)

# ==== Helpers ====
def get_readable_time(seconds: int) -> str:
    return time.strftime('%Hh:%Mm:%Ss', time.gmtime(seconds))

async def get_served_users():
    return [user async for user in usersdb.find({"user_id": {"$gt": 0}})]

async def get_served_chats():
    return [chat async for chat in chatsdb.find({"chat_id": {"$lt": 0}})]

# ==== Commands ====
@app.on_message(filters.command("status") & sudo_admin_filter)
async def status_command(client: Client, message: Message):
    uptime = get_readable_time(time.time() - START_TIME)
    served_users = await usersdb.count_documents({})
    served_chats = await chatsdb.count_documents({})

    text = (
        f"<b>🤖 Bot Status</b>\n\n"

        f"👥 Users: <code>{served_users}</code>\n"

        f"👨‍👩‍👧‍👦 Chats: <code>{served_chats}</code>\n\n"

        f"⚙️ Platform: <code>{platform.system()} {platform.release()}</code>\n"

        f"📦 Python: <code>{platform.python_version()}</code>\n"

        f"⏱ Uptime: <code>{uptime}</code>\n"

        f"🧠 Memory Usage: <code>{psutil.virtual_memory().percent}%</code>\n"
    )

    await message.reply_text(text)

@app.on_message(filters.command("renew") & sudo_admin_filter)
async def restart_bot(client: Client, message: Message):
    await message.reply_text("♻️ Restarting bot...")
    await client.send_message(LOGGER_GROUP_ID, f"♻️ Bot restarting by [{message.from_user.first_name}](tg://user?id={message.from_user.id})")
    await asyncio.sleep(2)
    os.execv(sys.executable, [sys.executable, "-m", "cast"])

@app.on_message(filters.command("shutdown") & sudo_admin_filter)
async def shutdown_bot(client: Client, message: Message):
    await message.reply_text("⚠️ Shutting down bot...")
    await client.send_message(LOGGER_GROUP_ID, f"⚠️ Bot shutdown by [{message.from_user.first_name}](tg://user?id={message.from_user.id})")
    await asyncio.sleep(2)
    os._exit(0)

@app.on_message(filters.command("broadcastlog") & sudo_admin_filter)
async def broadcast_log(client: Client, message: Message):
    logs = await broadcast_logs.find().sort("timestamp", -1).to_list(length=10)
    if not logs:
        return await message.reply_text("No broadcasts logged yet.")

    lines = []
    for i, log in enumerate(logs, 1):
        lines.append(
            f"<b>{i}. {log['sender_name']}</b>\n"
            f"🗓 {log['timestamp']}\n"
            f"✅ Sent: <code>{log['sent']}</code> | ❌ Failed: <code>{log['failed']}</code>\n"
            f"⏱ Duration: <code>{log['duration']}s</code>\n"
            f"📣 Mode: <code>{log['mode']}</code>\n"
        )

    await message.reply_text("\n".join(lines), disable_web_page_preview=True)


@app.on_message(filters.command("broadcast") & sudo_admin_filter)
async def broadcast_command(client: Client, message: Message):
    from_text = message.text.lower()
    mode = "forward" if "-forward" in from_text else "copy"

    if "-all" in from_text:
        target_users = [doc["user_id"] for doc in await get_served_users()]
        target_chats = [doc["chat_id"] for doc in await get_served_chats()]
    elif "-users" in from_text:
        target_users = [doc["user_id"] for doc in await get_served_users()]
        target_chats = []
    elif "-chats" in from_text:
        target_chats = [doc["chat_id"] for doc in await get_served_chats()]
        target_users = []
    else:
        return await message.reply_text("Please use a valid tag: -all, -users, -chats")

    content = message.reply_to_message or None
    if not content:
        msg_txt = from_text.replace("/broadcast", "")
        for tag in ["-all", "-users", "-chats", "-forward"]:
            msg_txt = msg_txt.replace(tag, "")
        msg_txt = msg_txt.strip()
        if not msg_txt:
            return await message.reply_text("Provide a message or reply to one.")
        content = msg_txt

    sent = failed = 0
    sent_users = sent_chats = 0
    total = len(target_users) + len(target_chats)
    start_time = time.time()

    status_msg = await message.reply("Broadcast started...")

    async def send(chat_id):
        nonlocal sent, failed, sent_users, sent_chats
        for _ in range(2):
            try:
                if isinstance(content, str):
                    await client.send_message(chat_id, content)
                else:
                    if mode == "forward":
                        await client.forward_messages(chat_id, message.chat.id, content.id)
                    else:
                        await content.copy(chat_id)

                sent += 1
                if chat_id in target_users:
                    sent_users += 1
                else:
                    sent_chats += 1
                return
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except RPCError:
                await asyncio.sleep(0.5)
        failed += 1

    async def batch_send(targets):
        BATCH_SIZE = 500
        for i in range(0, len(targets), BATCH_SIZE):
            batch = targets[i:i + BATCH_SIZE]
            await asyncio.gather(*[send(chat_id) for chat_id in batch])
            await asyncio.sleep(3)

            percent = round((sent + failed) / total * 100, 2)
            eta = (time.time() - start_time) / (sent + failed) * (total - (sent + failed)) if (sent + failed) else 0
            bar = f"[{'█' * int(percent // 5)}{'░' * (20 - int(percent // 5))}]"
            await status_msg.edit_text(
                f"<b>📡 Broadcast Progress</b>\n\n"

                f"{bar} <code>{percent}%</code>\n"

                f"✅ Sent: <code>{sent}</code>\n"

                f"❌ Failed: <code>{failed}</code>\n"

                f"⏱ ETA: <code>{int(eta)}s</code>\n"
            )

    await batch_send(target_users + target_chats)

    end = time.time() - start_time
    await status_msg.edit_text(
        f"<b>✅ Broadcast Complete</b>\n\n"

        f"Mode: <code>{mode}</code>\n"

        f"Sent: <code>{sent}</code>\n"

        f"Failed: <code>{failed}</code>\n"

        f"Users: <code>{sent_users}</code>\n"

        f"Chats: <code>{sent_chats}</code>\n"

        f"Duration: <code>{int(end)}s</code>\n"
    )

    await broadcast_logs.insert_one({
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "sender_id": message.from_user.id,
        "sender_name": message.from_user.first_name,
        "mode": mode,
        "sent": sent,
        "failed": failed,
        "duration": int(end),
    })

# ==== RUN ====
if __name__ == "__main__":
    print(">> Bot Running...")
    app.run()
