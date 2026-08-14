import traceback
import asyncio

from Data import Data
from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram import filters

from StringSessionBot.generate import generate_session, active_tasks, cancel_generation

ERROR_MESSAGE = (
    "⚠️ ᴏᴏᴘs! ᴀɴ ᴇxᴄᴇᴘᴛɪᴏɴ ᴏᴄᴄᴜʀʀᴇᴅ!\n\n"
    "**ᴇʀʀᴏʀ**: {}\n\n"
    "ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ."
)


@Client.on_callback_query()
async def _callbacks(bot: Client, callback_query: CallbackQuery):
    try:
        query = callback_query.data.lower()
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.id
        user_id = callback_query.from_user.id

        bot_info = await bot.get_me()
        mention = bot_info.mention

        # ================= HOME =================
        if query == "home":
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=Data.START.format(
                    callback_query.from_user.mention,
                    mention
                ),
                reply_markup=Data.buttons,
            )

        # ================= ABOUT =================
        elif query == "about":
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=Data.ABOUT,
                disable_web_page_preview=True,
                reply_markup=Data.home_buttons,
            )

        # ================= HELP =================
        elif query == "help":
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="**ʜᴇʀᴇ ɪs ʜᴏᴡ ᴛᴏ ᴜsᴇ ᴍᴇ**\n\n" + Data.HELP,
                disable_web_page_preview=True,
                reply_markup=Data.home_buttons,
            )

        # ================= GENERATE =================
        elif query == "generate":
            await callback_query.message.reply(
                "ᴘʟᴇᴀsᴇ ᴄʜᴏᴏsᴇ ᴛʜᴇ ʟɪʙʀᴀʀʏ",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🧑‍💻 ᴘʏʀᴏɢʀᴀᴍ",
                                callback_data="pyrogram"
                            ),
                            InlineKeyboardButton(
                                "ᴛᴇʟᴇᴛʜᴏɴ 🧑‍💻",
                                callback_data="telethon"
                            ),
                        ]
                    ]
                ),
            )

        # ================= SESSION GENERATION =================
        elif query in ["pyrogram", "telethon"]:
            # Check if already generating for this user
            if user_id in active_tasks and not active_tasks[user_id].done():
                await callback_query.answer("⚠️ Already generating. Please wait or use /cancel.", show_alert=True)
                return

            await callback_query.answer("Generating session...")

            # Send a message with Cancel button
            cancel_buttons = InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_gen")]]
            )
            status_msg = await callback_query.message.reply(
                "🔄 **Session generation started...**\n"
                "You can click the **Cancel** button or send `/cancel` to abort.",
                reply_markup=cancel_buttons
            )

            try:
                # Start generation task
                task = asyncio.create_task(
                    generate_session(bot, status_msg, telethon=(query == "telethon"))
                )
                active_tasks[user_id] = task

                # Wait for completion
                await task

            except asyncio.CancelledError:
                await status_msg.edit(
                    "⛔ **Generation cancelled.**",
                    reply_markup=None
                )
                return

            except Exception as e:
                print(traceback.format_exc())
                await status_msg.edit(
                    ERROR_MESSAGE.format(str(e)),
                    reply_markup=None
                )
            finally:
                active_tasks.pop(user_id, None)

        # ================= CANCEL GENERATION =================
        elif query == "cancel_gen":
            user_id = callback_query.from_user.id
            if await cancel_generation(user_id):
                await callback_query.answer("✅ Generation cancelled.", show_alert=True)
                await callback_query.message.edit(
                    "⛔ **Generation cancelled.**",
                    reply_markup=None
                )
            else:
                await callback_query.answer("ℹ️ No active generation.", show_alert=True)

    except Exception as e:
        print(traceback.format_exc())
        try:
            await callback_query.message.reply(
                ERROR_MESSAGE.format(str(e))
            )
        except:
            pass


# ================= COMMAND: /cancel =================
@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(bot: Client, message: Message):
    user_id = message.from_user.id
    if await cancel_generation(user_id):
        await message.reply("⛔ **Generation cancelled.**")
    else:
        await message.reply("ℹ️ No active generation to cancel.")
