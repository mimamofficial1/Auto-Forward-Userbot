"""
SilentXForward/fsub.py
──────────────────────
Force Subscribe system.
Checks that the user has joined every required channel before using the bot.
"""

import logging
from pyrogram import Client, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelPrivate
from config import FSUB_CHANNELS, OWNER_ID, FSUB_BANNER
from SilentXForward import ui

logger = logging.getLogger(__name__)


async def check_fsub(client: Client, user_id: int) -> list:
    """
    Return the required channels the user has NOT joined.
    The owner is always exempt.
    """
    if not FSUB_CHANNELS:
        return []

    # owner bypass
    if OWNER_ID and user_id == OWNER_ID:
        return []

    not_joined = []
    for ch in FSUB_CHANNELS:
        try:
            member = await client.get_chat_member(ch["id"], user_id)
            if member.status in (
                enums.ChatMemberStatus.BANNED,
                enums.ChatMemberStatus.LEFT,
            ):
                not_joined.append(ch)
        except UserNotParticipant:
            not_joined.append(ch)
        except (ChatAdminRequired, ChannelPrivate):
            logger.warning(f"Cannot check membership for channel {ch['id']} — bot may not be admin")
        except Exception as e:
            logger.warning(f"FSUB check error for {ch['id']}: {e}")

    return not_joined


def _caption(first_name: str) -> str:
    return ui.screen(
        "🔒", "Join to continue",
        f"Hello {ui.esc(first_name)},",
        f"To use {ui.BRAND} you need to be a member of our channel(s).\n"
        "Join using the buttons below, then tap <b>I've Joined</b>.",
    )


async def _join_markup(client, not_joined: list) -> InlineKeyboardMarkup:
    buttons = []
    for i, ch in enumerate(not_joined, 1):
        try:
            chat = await client.get_chat(ch["id"])
            title = chat.title or f"Channel {i}"
        except Exception:
            title = f"Channel {i}"

        link = ch.get("link")
        if not link:
            try:
                link = await client.export_chat_invite_link(ch["id"])
            except Exception:
                link = "https://t.me"

        buttons.append([InlineKeyboardButton(f"📢 Join {ui.trim(title, 40)}", url=link)])

    buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="fsub_verify")])
    return InlineKeyboardMarkup(buttons)


async def send_fsub_message(client, message, not_joined: list):
    """Send the join prompt (banner image when configured) with the join buttons."""
    markup = await _join_markup(client, not_joined)
    caption = _caption(message.from_user.first_name)

    if FSUB_BANNER:
        await message.reply_photo(photo=FSUB_BANNER, caption=caption,
                                  parse_mode=enums.ParseMode.HTML, reply_markup=markup)
    else:
        await message.reply_text(caption, parse_mode=enums.ParseMode.HTML, reply_markup=markup)


async def fsub_verify_callback(client, callback_query):
    """Handle the “I've Joined” button."""
    user_id = callback_query.from_user.id
    not_joined = await check_fsub(client, user_id)

    if not not_joined:
        await callback_query.answer("Verified — you can use the bot now. Send /start.", show_alert=True)
        await callback_query.message.delete()
        return

    await callback_query.answer(
        f"You still need to join {len(not_joined)} channel(s).",
        show_alert=True
    )
    markup = await _join_markup(client, not_joined)
    caption = _caption(callback_query.from_user.first_name)

    # edit the caption if the prompt is a photo, otherwise the text
    try:
        await callback_query.message.edit_caption(
            caption=caption, parse_mode=enums.ParseMode.HTML, reply_markup=markup)
    except Exception:
        try:
            await callback_query.message.edit_text(
                text=caption, parse_mode=enums.ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass  # unchanged content — nothing to update
