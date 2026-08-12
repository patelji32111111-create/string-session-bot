#!/usr/bin/env python3
"""
Session Generator Bot Module
Supports: Pyrogram (v2) and Telethon session generation
Commands: /start, /pyro, /telethon, /cancel
"""

import re
import asyncio
from pyrogram import Client, filters
from pyrogram.errors import (
    SessionPasswordNeeded,
    PasswordHashInvalid,
    FloodWait,
    ApiIdInvalid,
    PhoneCodeInvalid,
    PhoneCodeExpired
)
from pyrogram.types import Message
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    ApiIdInvalidError
)

# Import your env (or config) file – create env.py with BOT_TOKEN, API_ID, API_HASH, LOGGER_GROUP
try:
    import env
except ImportError:
    print("⚠️ env.py not found. Create env.py with BOT_TOKEN, API_ID, API_HASH, LOGGER_GROUP")
    env = None

# ================= GLOBALS =================
active_tasks = {}  # user_id -> asyncio.Task

# ================= LOG FUNCTION =================
async def send_log(bot, text):
    if not env or not hasattr(env, "LOGGER_GROUP") or not env.LOGGER_GROUP:
        return
    try:
        await bot.send_message(chat_id=int(env.LOGGER_GROUP), text=text)
    except Exception as e:
        print(f"Logger Error: {e}")

# ================= CANCEL FUNCTION =================
async def cancel_generation(user_id):
    task = active_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False

# ================= CORE GENERATOR =================
async def generate_session(bot, msg, telethon=False):
    user_id = msg.chat.id
    active_tasks[user_id] = asyncio.current_task()

    await msg.reply(
        "🚀 **Session Generation Started**\n"
        "You can send `/cancel` anytime to abort."
    )

    # ---------- API_ID ----------
    while True:
        try:
            api_id_msg = await bot.ask(
                user_id,
                "📌 **Send API_ID** (numbers only)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            if api_id_msg.text and api_id_msg.text.strip().isdigit():
                api_id = int(api_id_msg.text.strip())
                if 1 < api_id < 9999999999:
                    break
            await msg.reply("❌ Invalid API_ID. Must be a positive integer.")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            return

    # ---------- API_HASH ----------
    while True:
        try:
            api_hash_msg = await bot.ask(
                user_id,
                "📌 **Send API_HASH** (32 hex characters)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            api_hash = api_hash_msg.text.strip()
            if re.fullmatch(r'[a-fA-F0-9]{32}', api_hash):
                break
            await msg.reply("❌ Invalid API_HASH. Must be exactly 32 hex characters (0-9, a-f).")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            return

    # ---------- PHONE ----------
    while True:
        try:
            phone_msg = await bot.ask(
                user_id,
                "📱 **Send Phone Number** (with country code, e.g. +91...)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            phone = phone_msg.text.strip()
            if phone.startswith('+') and re.fullmatch(r'\+?\d{8,15}', phone):
                break
            await msg.reply("❌ Invalid phone. Use format +<country><number> (8-15 digits).")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            return

    await msg.reply("📨 Sending OTP...")

    # ---------- INIT CLIENT ----------
    try:
        if telethon:
            client = TelegramClient(StringSession(), api_id, api_hash)
        else:
            client = Client(
                name="session_gen",
                api_id=api_id,
                api_hash=api_hash,
                in_memory=True
            )
        await client.connect()
    except (ApiIdInvalid, ApiIdInvalidError):
        await msg.reply("❌ API_ID / API_HASH invalid. Check your credentials.")
        return

    # ---------- SEND CODE ----------
    try:
        if telethon:
            await client.send_code_request(phone)
        else:
            await client.send_code(phone)
    except (ApiIdInvalid, ApiIdInvalidError):
        await msg.reply("❌ API credentials invalid.")
        await client.disconnect()
        return
    except (FloodWait, FloodWaitError) as e:
        wait = e.value if hasattr(e, 'value') else e.x
        await msg.reply(f"⛔ FloodWait: {wait} seconds. Please wait.")
        await client.disconnect()
        return
    except Exception as e:
        await msg.reply(f"❌ Error sending code: {str(e)}")
        await client.disconnect()
        return

    # ---------- OTP ----------
    while True:
        try:
            otp_msg = await bot.ask(
                user_id,
                "🔐 **Send OTP** (numbers only)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            otp = otp_msg.text.replace(" ", "").strip()
            if otp.isdigit() and len(otp) >= 3:
                break
            await msg.reply("❌ Invalid OTP. Only numbers.")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            await client.disconnect()
            return

    # ---------- LOGIN ----------
    password = None
    try:
        if telethon:
            await client.sign_in(phone, otp)
        else:
            # For Pyrogram, we need the phone_code_hash from send_code
            # We'll fetch it from the client state
            try:
                # Re‑send code to get fresh phone_code_hash if needed
                sent_code = await client.send_code(phone)
                await client.sign_in(phone, sent_code.phone_code_hash, otp)
            except AttributeError:
                # Fallback: sign_in with just otp (older pyrogram)
                await client.sign_in(phone, otp)
    except (SessionPasswordNeeded, PasswordHashInvalidError):
        # ---------- 2FA PASSWORD ----------
        while True:
            try:
                pwd_msg = await bot.ask(
                    user_id,
                    "🔐 **2‑Step Verification Password** (or /skip)",
                    filters=filters.text & ~filters.command(["cancel"])
                )
                if pwd_msg.text.lower() == "/skip":
                    password = None
                    break
                if len(pwd_msg.text.strip()) >= 3:
                    password = pwd_msg.text.strip()
                    break
                await msg.reply("❌ Password too short (min 3 chars).")
            except asyncio.CancelledError:
                await msg.reply("⛔ Generation cancelled.")
                await client.disconnect()
                return

        try:
            if password:
                if telethon:
                    await client.sign_in(password=password)
                else:
                    await client.check_password(password=password)
            else:
                # Telethon doesn't support empty password
                if telethon:
                    await client.sign_in(password="")  # fallback
        except (PasswordHashInvalid, PasswordHashInvalidError):
            await msg.reply("❌ Wrong password. Please restart /pyro or /telethon.")
            await client.disconnect()
            return
    except (PhoneCodeInvalid, PhoneCodeInvalidError, PhoneCodeExpired, PhoneCodeExpiredError):
        await msg.reply("❌ Invalid or expired OTP. Please restart.")
        await client.disconnect()
        return
    except Exception as e:
        await msg.reply(f"❌ Login error: {str(e)}")
        await client.disconnect()
        return

    # ---------- GENERATE SESSION ----------
    try:
        if telethon:
            session_str = client.session.save()
        else:
            session_str = await client.export_session_string()
    except Exception as e:
        await msg.reply(f"❌ Session generation failed: {str(e)}")
        await client.disconnect()
        return

    await client.disconnect()

    # ---------- OUTPUT ----------
    output = f"✅ **Session Generated** ({'Telethon' if telethon else 'Pyrogram'})\n\n`{session_str}`"
    await msg.reply(output)

    # ---------- LOG TO GROUP ----------
    await send_log(
        bot,
        f"🔥 New session generated\n"
        f"User ID: `{user_id}`\n"
        f"Phone: `{phone}`\n"
        f"Type: {'Telethon' if telethon else 'Pyrogram'}"
    )

    # ---------- CLEANUP ----------
    active_tasks.pop(user_id, None)

# ================= COMMAND HANDLERS =================

async def start_cmd(client, message):
    await message.reply(
        "🎯 **Session Generator Bot**\n\n"
        "Send `/pyro` to generate a **Pyrogram v2** session.\n"
        "Send `/telethon` to generate a **Telethon** session.\n"
        "Send `/cancel` to abort any running generation.\n\n"
        "⚠️ You need: API_ID, API_HASH, Phone, OTP."
    )

async def pyro_gen(client, message):
    await generate_session(client, message, telethon=False)

async def telethon_gen(client, message):
    await generate_session(client, message, telethon=True)

async def cancel_cmd(client, message):
    user_id = message.chat.id
    if await cancel_generation(user_id):
        await message.reply("⛔ Generation cancelled.")
    else:
        await message.reply("ℹ️ No active generation to cancel.")

# ================= MAIN SETUP =================

def register_handlers(app):
    """Register all handlers on the given app instance."""
    app.on_message(filters.command("start") & filters.private)(start_cmd)
    app.on_message(filters.command("pyro") & filters.private)(pyro_gen)
    app.on_message(filters.command("telethon") & filters.private)(telethon_gen)
    app.on_message(filters.command("cancel") & filters.private)(cancel_cmd)

async def main():
    if not env or not hasattr(env, "BOT_TOKEN"):
        print("❌ BOT_TOKEN not found in env.py")
        print("Create env.py with: BOT_TOKEN, API_ID, API_HASH, LOGGER_GROUP (optional)")
        return

    app = Client(
        "session_bot",
        api_id=getattr(env, "API_ID", 0),
        api_hash=getattr(env, "API_HASH", ""),
        bot_token=env.BOT_TOKEN,
    )

    register_handlers(app)

    await app.start()
    print("🤖 Bot is running...")
    await asyncio.Event().wait()  # Keep running

if __name__ == "__main__":
    asyncio.run(main())
