"""
SilentXForward/logger.py
────────────────────────
Central log sender — sends formatted log messages to LOG_CHANNEL.
Import send_log() wherever you need to log an event.
"""

import logging
from datetime import datetime
from pyrogram import enums
from config import LOG_CHANNEL
from SilentXForward.ui import esc, code, kv, screen

logger = logging.getLogger(__name__)


async def send_log(client, text: str):
    """Send a log message to LOG_CHANNEL. Silently ignores if not configured."""
    if not LOG_CHANNEL:
        return
    try:
        await client.send_message(
            chat_id=LOG_CHANNEL,
            text=text,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.warning(f"Log send failed: {e}")


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


# ─── Event formatters ─────────────────────────────────────────────────────────
# Every log entry: icon + title, divider, then "Label · value" lines.

def _who(user) -> str:
    name = f"{user.first_name} {user.last_name or ''}".strip()
    return "\n".join([
        kv("User", esc(name)),
        kv("ID", code(user.id)),
        kv("Username", "@" + esc(user.username) if user.username else "—"),
    ])


def _entry(icon: str, title: str, *lines: str) -> str:
    return screen(icon, title, "\n".join(lines + (kv("Time", now()),)))


async def log_new_user(client, user):
    """Log when a new user starts the bot."""
    await send_log(client, _entry("👤", "New user", _who(user)))


async def log_login(client, user, phone: str):
    """Log when a user connects their Telegram account."""
    await send_log(client, _entry("🔑", "Account connected", _who(user), kv("Phone", code(phone))))


async def log_logout(client, user):
    """Log when a user disconnects."""
    await send_log(client, _entry("🚪", "Account disconnected", _who(user)))


async def log_source_added(client, user, source_title: str, source_id: int,
                           target_title: str, target_id: int):
    """Log when a source → target route is created."""
    await send_log(client, _entry(
        "✅", "Route created", kv("By", f"{esc(user.first_name)} {code(user.id)}"),
        kv("Source", f"{esc(source_title)} {code(source_id)}"),
        kv("Target", f"{esc(target_title)} {code(target_id)}")))


async def log_source_removed(client, user, source_title: str, source_id: int):
    """Log when a source is fully removed."""
    await send_log(client, _entry(
        "🗑", "Source removed", kv("By", f"{esc(user.first_name)} {code(user.id)}"),
        kv("Source", f"{esc(source_title)} {code(source_id)}")))


async def log_target_removed(client, user, source_title: str, source_id: int,
                             target_title: str, target_id: int):
    """Log when one target is removed from a source."""
    await send_log(client, _entry(
        "➖", "Target removed", kv("By", f"{esc(user.first_name)} {code(user.id)}"),
        kv("Source", f"{esc(source_title)} {code(source_id)}"),
        kv("Target", f"{esc(target_title)} {code(target_id)}")))


async def log_forward_success(client, source_title: str, source_id: int,
                              target_id: int, msg_count: int):
    """Log when messages are forwarded successfully."""
    await send_log(client, _entry(
        "📨", "Forwarded", kv("Source", f"{esc(source_title)} {code(source_id)}"),
        kv("Target", code(target_id)), kv("Messages", msg_count)))


async def log_forward_failed(client, source_id: int, target_id: int,
                             msg_count: int, error: str):
    """Log when forwarding fails."""
    await send_log(client, _entry(
        "❌", "Forward failed", kv("Source", code(source_id)), kv("Target", code(target_id)),
        kv("Messages", msg_count), kv("Error", code(str(error)[:200]))))
