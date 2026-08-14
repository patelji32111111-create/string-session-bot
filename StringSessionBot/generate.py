#!/usr/bin/env python3
"""
Session Generator Bot – Fixed Cancellation
Supports: Pyrogram and Telethon
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

# Import env (create env.py with BOT_TOKEN, API_ID, API_HASH, LOGGER_GROUP)
try:
    import env
except ImportError:
    env = None
    print("⚠️ env.py not found. Create env.py with BOT_TOKEN, API_ID, API_HASH, LOGGER_GROUP")

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

# ================= SAFE ASK WRAPPER =================
async def safe_ask(bot, user_id, text, filters=None, timeout=300):
    """
    Wrapper for bot.ask that catches CancelledError and returns None if cancelled.
    """
    try:
        msg = await bot.ask(user_id, text, filters=filters, timeout=timeout)
        return msg
    except asyncio.CancelledError:
        # Propagate cancellation upward
        raise
    except Exception as e:
        # If it's a timeout or other error, return None
        return None

# ================= CORE GENERATOR =================
async def generate_session(bot, msg, telethon=False):
    user_id = msg.chat.id
    task = asyncio.current_task()
    active_tasks[user_id] = task

    await msg.reply(
        "🚀 **Session Generation Started**\n"
        "You can send `/cancel` anytime to abort."
    )

    # ---------- API_ID ----------
    while True:
        try:
            api_id_msg = await safe_ask(
                bot, user_id,
                "📌 **Send API_ID** (numbers only)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            if api_id_msg is None:
                # Cancelled or timeout
                await msg.reply("⛔ Timeout or cancelled.")
                return
            text = api_id_msg.text.strip()
            if text.isdigit():
                api_id = int(text)
                if 1 < api_id < 9999999999:
                    break
            await msg.reply("❌ Invalid API_ID. Must be a positive integer.")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            active_tasks.pop(user_id, None)
            return

    # ---------- API_HASH ----------
    while True:
        try:
            api_hash_msg = await safe_ask(
                bot, user_id,
                "📌 **Send API_HASH** (32 hex characters)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            if api_hash_msg is None:
                await msg.reply("⛔ Timeout or cancelled.")
                return
            api_hash = api_hash_msg.text.strip()
            if re.fullmatch(r'[a-fA-F0-9]{32}', api_hash):
                break
            await msg.reply("❌ Invalid API_HASH. Must be exactly 32 hex characters (0-9, a-f).")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            active_tasks.pop(user_id, None)
            return

    # ---------- PHONE ----------
    while True:
        try:
            phone_msg = await safe_ask(
                bot, user_id,
                "📱 **Send Phone Number** (with country code, e.g. +91...)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            if phone_msg is None:
                await msg.reply("⛔ Timeout or cancelled.")
                return
            phone = phone_msg.text.strip()
            if phone.startswith('+') and re.fullmatch(r'\+?\d{8,15}', phone):
                break
            await msg.reply("❌ Invalid phone. Use format +<country><number> (8-15 digits).")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            active_tasks.pop(user_id, None)
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
        active_tasks.pop(user_id, None)
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
        active_tasks.pop(user_id, None)
        return
    except (FloodWait, FloodWaitError) as e:
        wait = e.value if hasattr(e, 'value') else e.x
        await msg.reply(f"⛔ FloodWait: {wait} seconds. Please wait.")
        await client.disconnect()
        active_tasks.pop(user_id, None)
        return
    except Exception as e:
        await msg.reply(f"❌ Error sending code: {str(e)}")
        await client.disconnect()
        active_tasks.pop(user_id, None)
        return

    # ---------- OTP ----------
    while True:
        try:
            otp_msg = await safe_ask(
                bot, user_id,
                "🔐 **Send OTP** (numbers only)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            if otp_msg is None:
                await msg.reply("⛔ Timeout or cancelled.")
                await client.disconnect()
                active_tasks.pop(user_id, None)
                return
            otp = otp_msg.text.replace(" ", "").strip()
            if otp.isdigit() and len(otp) >= 3:
                break
            await msg.reply("❌ Invalid OTP. Only numbers (at least 3 digits).")
        except asyncio.CancelledError:
            await msg.reply("⛔ Generation cancelled.")
            await client.disconnect()
            active_tasks.pop(user_id, None)
            return

    # ---------- LOGIN ----------
    password = None
    try:
        if telethon:
            await client.sign_in(phone, otp)
        else:
            # We need the phone_code_hash. We'll re‑send code to get it.
            sent_code = await client.send_code(phone)
            await client.sign_in(phone, sent_code.phone_code_hash, otp)
    except (SessionPasswordNeeded, PasswordHashInvalidError):
        # ---------- 2FA PASSWORD ----------
        while True:
            try:
                pwd_msg = await safe_ask(
                    bot, user_id,
                    "🔐 **2‑Step Verification Password** (or /skip)",
                    filters=filters.text & ~filters.command(["cancel"])
                )
                if pwd_msg is None:
                    await msg.reply("⛔ Timeout or cancelled.")
                    await client.disconnect()
                    active_tasks.pop(user_id, None)
                    return
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
                active_tasks.pop(user_id, None)
                return

        try:
            if password:
                if telethon:
                    await client.sign_in(password=password)
                else:
                    await client.check_password(password=password)
            else:
                # If no password, telethon may fail – we try sign_in with empty
                if telethon:
                    await client.sign_in(password="")
        except (PasswordHashInvalid, PasswordHashInvalidError):
            await msg.reply("❌ Wrong password. Please restart /pyro or /telethon.")
            await client.disconnect()
            active_tasks.pop(user_id, None)
            return
    except (PhoneCodeInvalid, PhoneCodeInvalidError, PhoneCodeExpired, PhoneCodeExpiredError):
        await msg.reply("❌ Invalid or expired OTP. Please restart.")
        await client.disconnect()
        active_tasks.pop(user_id, None)
        return
    except Exception as e:
        await msg.reply(f"❌ Login error: {str(e)}")
        await client.disconnect()
        active_tasks.pop(user_id, None)
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
        active_tasks.pop(user_id, None)
        return

    await client.disconnect()

    # ---------- OUTPUT ----------
    output = (
        f"✅ **Session Generated** ({'Telethon' if telethon else 'Pyrogram'})\n\n"
        f"`{session_str}`"
    )
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
