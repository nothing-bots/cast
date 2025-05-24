import sys
import os
import time
import asyncio
import platform
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
LOGGER_GROUP_ID = int(os.getenv("LOGGER_GROUP_ID", "-1002144355688"))

# ==== INIT ====
app = Client("BroadcastBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_DB_URI)
mongodb = mongo_client.deadline
usersdb = mongodb.tgusersdb
chatsdb = mongodb.chats

# ==== ADMINS ====
OWNER_ID = 7765692814
OWNER_ID2 = 6848223695
SECOND_OWNER_ID = 5350261891
ALLOWED_ADMINS = [OWNER_ID, SECOND_OWNER_ID, OWNER_ID2]
sudo_filter = filters.user(ALLOWED_ADMINS)

# ==== HELPERS ====
async def get_served_users():
    return [user async for user in usersdb.find({"user_id": {"$gt": 0}})]

async def get_served_chats():
    return [chat async for chat in chatsdb.find({"chat_id": {"$lt": 0}})]

def get_readable_time(seconds: int) -> str:
    return time.strftime('%Hh:%Mm:%Ss', time.gmtime(seconds))

# ==== STATUS ====
@app.on_message(filters.command("status") & sudo_filter)
async def status_command(client: Client, message: Message):
    uptime = get_readable_time(time.time() - psutil.boot_time())
    users = await usersdb.count_documents({})
    chats = await chatsdb.count_documents({})
    mem = psutil.virtual_memory()

    await message.reply_text(
        f"<b>🤖 Bot Status</b>\n\n"
        f"👥 Users: <code>{users}</code>\n"
        f"👨‍👩‍👧‍👦 Chats: <code>{chats}</code>\n"
        f"🕐 Uptime: <code>{uptime}</code>\n"
        f"⚙️ Platform: <code>{platform.system()} {platform.release()}</code>\n"
        f"📦 Python: <code>{platform.python_version()}</code>\n"
        f"🧠 Memory Usage: <code>{mem.percent}%</code>"
    )

# ==== RESTART ====
@app.on_message(filters.command("renew") & sudo_filter)
async def restart_bot(client: Client, message: Message):
    await message.reply_text("♻️ Restarting bot...")
    await client.send_message(LOGGER_GROUP_ID, f"♻️ Bot is restarting...\n<b>Triggered By:</b> <a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>")
    await asyncio.sleep(2)
    os.execv(sys.executable, [sys.executable, "-m", "cast"])

# ==== SHUTDOWN ====
@app.on_message(filters.command("shutdown") & sudo_filter)
async def shutdown_bot(client: Client, message: Message):
    await message.reply_text("⚠️ Shutting down bot...")
    await client.send_message(LOGGER_GROUP_ID, f"⚠️ Bot is shutting down...\n<b>Triggered By:</b> <a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>")
    await asyncio.sleep(2)
    os._exit(0)

# ==== BROADCAST ====
@app.on_message(filters.command("broadcast") & sudo_filter)
async def broadcast_command(client: Client, message: Message):
    args = message.text.lower()
    mode = "forward" if "-forward" in args else "copy"

    # Targets
    users, chats = [], []
    if "-all" in args:
        users = [u["user_id"] for u in await get_served_users()]
        chats = [c["chat_id"] for c in await get_served_chats()]
    elif "-users" in args:
        users = [u["user_id"] for u in await get_served_users()]
    elif "-chats" in args:
        chats = [c["chat_id"] for c in await get_served_chats()]
    else:
        return await message.reply("Use -all, -users, or -chats")

    content = message.reply_to_message
    if not content and len(args.split()) > 1:
        content = args.replace("/broadcast", "").replace("-forward", "").replace("-all", "").replace("-users", "").replace("-chats", "").strip()
        if not content:
            return await message.reply("Reply to a message or provide text.")
    elif not content:
        return await message.reply("Reply to a message or provide text.")

    total = len(users) + len(chats)
    status_msg = await message.reply("🚀 Broadcast started...")
    sent = failed = 0

    await client.send_message(LOGGER_GROUP_ID, f"📢 <b>Broadcast Started</b>\nBy: <a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>\nMode: <code>{mode}</code>\nTargets: <code>{total}</code>")

    async def send(chat_id):
        nonlocal sent, failed
        for _ in range(2):
            try:
                if isinstance(content, str):
                    await client.send_message(chat_id, content)
                elif mode == "forward":
                    await client.forward_messages(chat_id, content.chat.id, content.id)
                else:
                    await content.copy(chat_id)
                sent += 1
                return
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except RPCError:
                await asyncio.sleep(0.5)
        failed += 1

    async def batch_send(targets):
        for i in range(0, len(targets), 100):
            batch = targets[i:i + 100]
            await asyncio.gather(*(send(cid) for cid in batch))
            await asyncio.sleep(2)
            percent = round((sent + failed) / total * 100, 2)
            await status_msg.edit_text(f"<b>📡 Progress</b>\nSent: {sent} | Failed: {failed}\nDone: {percent}%")

    await batch_send(users + chats)

    await status_msg.edit_text(
        f"<b>✅ Broadcast Complete</b>\n\n"
        f"Mode: <code>{mode}</code>\n"
        f"Total: <code>{total}</code>\n"
        f"✅ Sent: <code>{sent}</code>\n"
        f"❌ Failed: <code>{failed}</code>"
    )
# ==== RUN ====
if __name__ == "__main__":
    print(">> Starting Bot...")
    app.run()
