import os
import time
import asyncio
import signal
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
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", "-1002144355688"))

# ==== INIT ====
app = Client("BroadcastBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_DB_URI)
mongodb = mongo_client.deadline
usersdb = mongodb.tgusersdb
chatsdb = mongodb.chats

START_TIME = time.time()

OWNER_ID = 7765692814
OWNER_ID2 = 6848223695
SECOND_OWNER_ID = 5350261891
ALLOWED_ADMINS = [OWNER_ID, SECOND_OWNER_ID, OWNER_ID2]
sudo_admin_filter = filters.user(ALLOWED_ADMINS)

# ==== DB ====
async def get_served_users():
    return [user async for user in usersdb.find({"user_id": {"$gt": 0}})]

async def get_served_chats():
    return [chat async for chat in chatsdb.find({"chat_id": {"$lt": 0}})]

# ==== UPTIME ====
def get_readable_time(seconds: int) -> str:
    return time.strftime('%Hh:%Mm:%Ss', time.gmtime(seconds))

# ==== STATUS ====
@app.on_message(filters.command("status") & sudo_admin_filter)
async def bot_status(_, message: Message):
    current_time = time.time()
    uptime = get_readable_time(int(current_time - START_TIME))
    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent()

    users = await get_served_users()
    chats = await get_served_chats()

    await message.reply_text(
        f"🔧 <b>Bot Status</b>\n\n"
        f"⏱ Uptime: <code>{uptime}</code>\n"
        f"👤 Served Users: <code>{len(users)}</code>\n"
        f"💬 Served Chats: <code>{len(chats)}</code>\n"
        f"💾 RAM Usage: <code>{memory.percent}%</code>\n"
        f"⚙ CPU Usage: <code>{cpu}%</code>"
    )


# ==== RESTART ====
@app.on_message(filters.command("renew") & sudo_admin_filter)
async def restart_bot(_, message: Message):
    await message.reply("♻️ Restarting...")

    if LOG_GROUP_ID:
        try:
            await app.send_message(LOG_GROUP_ID, "♻️ <b>Bot is restarting...</b>")
        except Exception:
            pass

    await app.stop()
    os.execl(sys.executable, sys.executable, *sys.argv)

# ==== SHUTDOWN ====
@app.on_message(filters.command("shutdown") & sudo_admin_filter)
async def shutdown_bot(_, message: Message):
    await message.reply("🛑 Shutting down...")

    if LOG_GROUP_ID:
        try:
            await app.send_message(LOG_GROUP_ID, "🛑 <b>Bot has been shut down!</b>")
        except Exception:
            pass

    await app.stop()
    os.kill(os.getpid(), signal.SIGTERM)

# ==== BROADCAST ====
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

    if not target_chats and not target_users:
        return await message.reply_text("No targets found.")

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
            await asyncio.sleep(2)

            percent = round((sent + failed) / total * 100, 2)
            eta = (time.time() - start_time) / (sent + failed) * (total - (sent + failed)) if (sent + failed) else 0
            bar = f"[{'█' * int(percent // 5)}{'░' * (20 - int(percent // 5))}]"
            await status_msg.edit_text(
                f"<b>📡 Broadcast Progress</b>\n\n"
                f"{bar} <code>{percent}%</code>\n"
                f"✅ Sent: <code>{sent}</code>\n"
                f"❌ Failed: <code>{failed}</code>\n"
                f"⏱ ETA: <code>{int(eta)}s</code>"
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
        f"Duration: <code>{int(end)}s</code>"
    )

# ==== RUN ====
if __name__ == "__main__":
    print(">> Bot Running...")
    app.run()
