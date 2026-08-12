import asyncio
import re
import env
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


# ================= LOG FUNCTION =================
async def send_log(bot, text):
    """Send a log message to the configured LOGGER_GROUP."""
    if not env.LOGGER_GROUP:
        return
    try:
        await bot.send_message(int(env.LOGGER_GROUP), text)
    except Exception as e:
        print(f"Logger Error: {e}")


# ================= CANCEL HANDLER =================
# Store active generation tasks to cancel them if needed
active_tasks = {}


async def cancel_generation(user_id):
    """Cancel an ongoing generation task for a user."""
    task = active_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message):
    """Cancel the current session generation for the user."""
    user_id = message.chat.id
    if await cancel_generation(user_id):
        await message.reply("❌ Generation cancelled.")
    else:
        await message.reply("ℹ️ No active generation to cancel.")


# ================= SESSION GENERATOR =================
async def generate_session(bot, msg, telethon=False):
    """
    Main session generation flow.
    telethon=True -> generates Telethon session string
    telethon=False -> generates Pyrogram session string (default)
    """
    user_id = msg.chat.id
    # Store the task so it can be cancelled
    active_tasks[user_id] = asyncio.current_task()

    try:
        await msg.reply("🚀 Session generation started...\n"
                        "Send /cancel anytime to abort.")

        # ================= API_ID =================
        while True:
            api_id_msg = await bot.ask(
                user_id,
                "📝 Send **API_ID** (numbers only)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            if api_id_msg.text.strip().isdigit():
                api_id = int(api_id_msg.text.strip())
                if 1 <= api_id <= 999999999:  # reasonable range
                    break
                else:
                    await msg.reply("❌ API_ID must be a positive integer.")
            else:
                await msg.reply("❌ Invalid API_ID. Please send numbers only.")

        # ================= API_HASH =================
        while True:
            api_hash_msg = await bot.ask(
                user_id,
                "📝 Send **API_HASH** (32 hexadecimal characters)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            api_hash = api_hash_msg.text.strip()
            if re.fullmatch(r'[a-fA-F0-9]{32}', api_hash):
                break
            await msg.reply("❌ Invalid API_HASH. Must be exactly 32 hex chars (a-f, 0-9).")

        # ================= PHONE =================
        while True:
            phone_msg = await bot.ask(
                user_id,
                "📱 Send **Phone Number** (with country code, e.g. +91...)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            phone = phone_msg.text.strip()
            if phone.startswith('+') and re.fullmatch(r'\+\d{8,15}', phone):
                break
            await msg.reply("❌ Invalid phone number. Use format +<country><number> (8‑15 digits).")

        await msg.reply("📨 Sending OTP...")

        # ================= CLIENT INIT =================
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
            await msg.reply("❌ API_ID / API_HASH are invalid. Check your credentials.")
            return

        # ================= SEND CODE =================
        try:
            if telethon:
                code = await client.send_code_request(phone)
            else:
                code = await client.send_code(phone)
        except (ApiIdInvalid, ApiIdInvalidError):
            await msg.reply("❌ API credentials invalid.")
            await client.disconnect()
            return
        except FloodWait as e:
            await msg.reply(f"⛔ FloodWait: wait **{e.value}** seconds.")
            await client.disconnect()
            return
        except Exception as e:
            await msg.reply(f"❌ Error sending code: {str(e)}")
            await client.disconnect()
            return

        # ================= OTP =================
        while True:
            otp_msg = await bot.ask(
                user_id,
                "🔐 Send **OTP** (numbers only)",
                filters=filters.text & ~filters.command(["cancel"])
            )
            otp = otp_msg.text.replace(" ", "")
            if otp.isdigit():
                break
            await msg.reply("❌ Invalid OTP. Send digits only.")

        # ================= LOGIN =================
        password = None
        try:
            if telethon:
                await client.sign_in(phone, otp)
            else:
                await client.sign_in(phone, code.phone_code_hash, otp)
        except (PhoneCodeInvalid, PhoneCodeInvalidError):
            await msg.reply("❌ Invalid OTP. Please restart the process with /start.")
            await client.disconnect()
            return
        except (PhoneCodeExpired, PhoneCodeExpiredError):
            await msg.reply("❌ OTP expired. Please restart.")
            await client.disconnect()
            return
        except SessionPasswordNeeded:
            # ================= PASSWORD =================
            while True:
                password_msg = await bot.ask(
                    user_id,
                    "🔐 2‑Step Verification enabled.\n"
                    "Send your **password** or /skip to skip (if no password set).",
                    filters=filters.text & ~filters.command(["cancel"])
                )
                text = password_msg.text
                if text.lower() == "/skip":
                    password = None
                    break
                if len(text) >= 3:
                    password = text
                    break
                await msg.reply("❌ Password too short. Minimum 3 characters.")
            try:
                if telethon:
                    if password:
                        await client.sign_in(password=password)
                    else:
                        # Telethon does not support empty password; if skipped, we assume no 2FA
                        pass
                else:
                    if password:
                        await client.check_password(password=password)
                    else:
                        # Pyrogram can handle empty password by not calling check_password
                        pass
            except (PasswordHashInvalid, PasswordHashInvalidError):
                await msg.reply("❌ Wrong password. Please restart.")
                await client.disconnect()
                return
        except FloodWait as e:
            await msg.reply(f"⛔ Login FloodWait: {e.value} seconds.")
            await client.disconnect()
            return
        except Exception as e:
            await msg.reply(f"❌ Login error: {str(e)}")
            await client.disconnect()
            return

        # ================= GENERATE SESSION =================
        try:
            if telethon:
                session_str = client.session.save()
            else:
                session_str = await client.export_session_string()
        except Exception as e:
            await msg.reply(f"❌ Failed to generate session: {str(e)}")
            await client.disconnect()
            return

        await client.disconnect()

        # ================= OUTPUT =================
        await msg.reply(f"✅ **SESSION GENERATED** ({"Telethon" if telethon else "Pyrogram"}):\n\n`{session_str}`")

        # Log to group (if set)
        await send_log(
            bot,
            f"✅ New session generated\n"
            f"User: `{user_id}`\n"
            f"Phone: `{phone}`\n"
            f"Type: {'Telethon' if telethon else 'Pyrogram'}"
        )

    except asyncio.CancelledError:
        await msg.reply("⏹️ Generation cancelled.")
        await send_log(bot, f"❌ Cancelled by user: {user_id}")
    finally:
        # Remove task from active dict
        active_tasks.pop(user_id, None)


# ================= COMMAND HANDLERS =================
@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    """Start command – show available options."""
    await message.reply(
        "🤖 **Session Generator Bot**\n\n"
        "Send /pyro to generate a **Pyrogram** session.\n"
        "Send /telethon to generate a **Telethon** session.\n"
        "Send /cancel to abort any running generation."
    )


@Client.on_message(filters.command("pyro") & filters.private)
async def pyro_gen(client, message):
    """Generate Pyrogram session."""
    await generate_session(client, message, telethon=False)


@Client.on_message(filters.command("telethon") & filters.private)
async def telethon_gen(client, message):
    """Generate Telethon session."""
    await generate_session(client, message, telethon=True)


# ================= MAIN =================
async def main():
    """Start the bot."""
    # Ensure env variables are set
    if not hasattr(env, "BOT_TOKEN"):
        raise ValueError("BOT_TOKEN not found in env.py")
    if not hasattr(env, "LOGGER_GROUP"):
        env.LOGGER_GROUP = None  # optional

    app = Client(
        "session_bot",
        api_id=env.API_ID,          # Your bot's API_ID (from my.telegram.org)
        api_hash=env.API_HASH,      # Your bot's API_HASH
        bot_token=env.BOT_TOKEN
    )

    # Register handlers
    app.on_message(filters.command("start") & filters.private)(start_cmd)
    app.on_message(filters.command("pyro") & filters.private)(pyro_gen)
    app.on_message(filters.command("telethon") & filters.private)(telethon_gen)
    app.on_message(filters.command("cancel") & filters.private)(cancel_cmd)

    await app.start()
    print("🤖 Bot is running...")
    await asyncio.Event().wait()  # keep running


if __name__ == "__main__":
    asyncio.run(main())
