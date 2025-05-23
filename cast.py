import time
import asyncio
import os
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# ==== LOAD ENV ====
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_DB_URI = os.getenv("MONGO_DB_URI")

# ==== CONSTANTS ====
REQUEST_LIMIT = 50
BATCH_SIZE = 600
BATCH_DELAY = 3
MAX_RETRIES = 2

# ==== INIT ====
app = Client("BroadcastBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_DB_URI)
mongodb = mongo_client.deadline
usersdb = mongodb.tgusersdb
chatsdb = mongodb.chats

# ==== DB HELPERS ====
async def get_served_users() -> list:
    return [user async for user in usersdb.find({"user_id": {"$gt": 0}})]

async def get_served_chats() -> list:
    return [chat async for chat in chatsdb.find({"chat_id": {"$lt": 0}})]



OWNER_ID = 7765692814
OWNER_ID2 = 6848223695
SECOND_OWNER_ID = 5350261891


ALLOWED_ADMINS = [OWNER_ID, SECOND_OWNER_ID, OWNER_ID2]
sudo_admin_filter = filters.user(ALLOWED_ADMINS)


# ==== BROADCAST ====
@app.on_message(filters.command("broadcast") & sudo_admin_filter)
async def broadcast_command(client: Client, message: Message):
    command_text = message.text.lower()
    mode = "forward" if "-forward" in command_text else "copy"

    if "-all" in command_text:
        target_users = [doc["user_id"] for doc in await get_served_users()]
        target_chats = [doc["chat_id"] for doc in await get_served_chats()]
    elif "-users" in command_text:
        target_users = [doc["user_id"] for doc in await get_served_users()]
        target_chats = []
    elif "-chats" in command_text:
        target_chats = [doc["chat_id"] for doc in await get_served_chats()]
        target_users = []
    else:
        return await message.reply_text("Please use a valid tag: -all, -users, -chats")

    if not target_chats and not target_users:
        return await message.reply_text("No targets found for broadcast.")

    content_message = message.reply_to_message or None
    if not content_message:
        stripped_text = command_text
        for tag in ["-all", "-users", "-chats", "-forward"]:
            stripped_text = stripped_text.replace(tag, "")
        stripped_text = stripped_text.replace("/broadcast", "").strip()

        if not stripped_text:
            return await message.reply_text("Please provide a message or reply to one.")
        content_message = stripped_text

    start_time = time.time()
    sent_count = failed_count = 0
    sent_to_users = sent_to_chats = 0

    targets = target_chats + target_users
    total_targets = len(targets)

    status_msg = await message.reply_text(f"Broadcast started in `{mode}` mode...\n\nProgress: `0%`")

    async def send_with_retries(chat_id):
        nonlocal sent_count, failed_count, sent_to_users, sent_to_chats
        for _ in range(MAX_RETRIES):
            try:
                if isinstance(content_message, str):
                    await client.send_message(chat_id, content_message)
                else:
                    if mode == "forward":
                        await client.forward_messages(
                            chat_id=chat_id,
                            from_chat_id=message.chat.id,
                            message_ids=content_message.id
                        )
                    else:
                        await content_message.copy(chat_id)
                sent_count += 1
                if chat_id in target_users:
                    sent_to_users += 1
                else:
                    sent_to_chats += 1
                return
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except RPCError:
                await asyncio.sleep(0.5)
        failed_count += 1

    async def broadcast_targets(target_list):
        for i in range(0, len(target_list), BATCH_SIZE):
            batch = target_list[i:i + BATCH_SIZE]
            tasks = [send_with_retries(chat_id) for chat_id in batch]
            for j in range(0, len(tasks), REQUEST_LIMIT):
                await asyncio.gather(*tasks[j:j+REQUEST_LIMIT])
            await asyncio.sleep(BATCH_DELAY)

            percent = round((sent_count + failed_count) / total_targets * 100, 2)
            elapsed = time.time() - start_time
            eta = (elapsed / (sent_count + failed_count)) * (total_targets - (sent_count + failed_count)) if (sent_count + failed_count) else 0
            eta_formatted = f"{int(eta//60)}m {int(eta%60)}s"
            bar = f"[{'█' * int(percent//5)}{'░' * (20-int(percent//5))}]"

            await status_msg.edit_text(
                f"<b>🔔 Broadcast Progress:</b>\n"
                f"{bar} <code>{percent}%</code>\n"
                f"✅ Sent: <code>{sent_count}</code> 🟢\n"
                f"⛔ Failed: <code>{failed_count}</code> 🔴\n"
                f"🕰 ETA: <code>{eta_formatted}</code> ⏳"
            )

    await broadcast_targets(targets)

    total_time = round(time.time() - start_time, 2)
    await status_msg.edit_text(
        f"<b>✅ Broadcast Report 📢</b>\n\n"
        f"Mode: <code>{mode}</code>\n"
        f"Total Targets: <code>{total_targets}</code>\n"
        f"Successful: <code>{sent_count}</code> 🟢\n"
        f"  ├─ Users: <code>{sent_to_users}</code>\n"
        f"  └─ Chats: <code>{sent_to_chats}</code>\n"
        f"Failed: <code>{failed_count}</code> 🔴\n"
        f"Time Taken: <code>{total_time}</code> seconds ⏰"
    )

# ==== RUN ====
if __name__ == "__main__":
    print(">> Starting Broadcast Bot...")
    app.run()
