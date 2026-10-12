import asyncio
import logging

from pyrogram import Client, filters, enums, ContinuePropagation
from pyrogram.types import Message
from pyrogram.errors import (
    PhoneNumberInvalid, PhoneCodeInvalid, PhoneCodeExpired,
    SessionPasswordNeeded, PasswordHashInvalid, PeerIdInvalid,
)

import config as cfg
from SilentXForward import database, ui
from SilentXForward.ui import esc, code, note, screen, usage, kv, bullets, numbered, quote, btn, kb, nav
from SilentXForward.fsub import check_fsub, send_fsub_message, fsub_verify_callback
from SilentXForward.logger import (
    log_new_user, log_login, log_logout,
    log_source_added, log_source_removed, log_target_removed
)
from SilentXForward.cover_copy import copy_keep_cover
from SilentXForward.forward import chat_display_name

logger = logging.getLogger(__name__)

HTML = enums.ParseMode.HTML
START_IMAGE = "https://files.catbox.moe/oht30s.jpg"

login_states = {}


# ==================== SMALL HELPERS ====================

async def send(message, text: str, markup=None):
    """Reply with HTML, no link previews."""
    return await message.reply_text(ui.finish(text), parse_mode=HTML, reply_markup=markup, disable_web_page_preview=True)


async def edit(message, text: str, markup=None):
    return await message.edit_text(ui.finish(text), parse_mode=HTML, reply_markup=markup, disable_web_page_preview=True)


async def send_long(message, text: str, markup=None, limit: int = 3800):
    """Telegram caps a message at 4096 chars — split long lists on paragraph boundaries."""
    if len(text) <= limit:
        return await send(message, text, markup)
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    parts.append(cur)
    for i, part in enumerate(parts):
        await send(message, part, markup if i == len(parts) - 1 else None)


async def try_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


def fmt_delay(value) -> str:
    return f"{float(value):g} s"


async def is_staff(user_id: int) -> bool:
    """Owner, or an admin added by the owner."""
    if not cfg.OWNER_ID:
        return False
    if user_id == cfg.OWNER_ID:
        return True
    try:
        return await database.is_admin(cfg.OWNER_ID, user_id)
    except Exception:
        logger.exception("is_staff: admin lookup failed")
        return False


# ==================== OWNER / ADMIN CHECKS ====================

def owner_only(func):
    """Only OWNER_ID may use the command."""
    async def wrapper(client, message: Message):
        if cfg.OWNER_ID and message.from_user.id != cfg.OWNER_ID:
            return await send(message, ui.ACCESS_DENIED_OWNER)
        return await func(client, message)
    wrapper.__name__ = func.__name__
    return wrapper


def admin_only(func):
    """OWNER_ID or an admin added with /addadmin."""
    async def wrapper(client, message: Message):
        if not await is_staff(message.from_user.id):
            return await send(message, ui.ACCESS_DENIED_STAFF)
        return await func(client, message)
    wrapper.__name__ = func.__name__
    return wrapper


# ==================== GLOBAL BAN CHECK ====================
# A banned user's private messages stop here, so /ban really works.

@Client.on_message(filters.private, group=-1)
async def global_ban_check(client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    if cfg.OWNER_ID and user_id == cfg.OWNER_ID:
        return
    try:
        # record every interacting user (also those who started before this was added)
        await database.save_user(user_id)
    except Exception:
        pass
    try:
        banned = await database.is_banned(cfg.OWNER_ID, user_id)
    except Exception:
        logger.exception("global_ban_check: is_banned lookup failed")
        banned = False
    if banned:
        try:
            await send(message, ui.BANNED_TEXT)
        except Exception:
            pass
        message.stop_propagation()


# ==================== CHAT LOOKUP ====================

async def smart_get_chat(client, chat_id, user_id):
    from SilentXForward.forward import active_userbots
    ub = active_userbots.get(user_id)
    if ub and ub.is_connected:
        try:
            return await ub.get_chat(chat_id)
        except PeerIdInvalid:
            logger.info(f"PeerIdInvalid for {chat_id} — trying dialogs...")
            try:
                async for dialog in ub.get_dialogs():
                    if dialog.chat.id == int(chat_id):
                        return dialog.chat
            except Exception as e:
                logger.warning(f"Dialog iteration failed: {e}")
            try:
                return await ub.get_chat(chat_id)
            except Exception as e:
                logger.warning(f"Userbot still can't get {chat_id}: {e}")
        except Exception as e:
            logger.warning(f"Userbot get_chat failed ({chat_id}): {e}")
    return await client.get_chat(chat_id)


# ==================== START / GUIDE / ABOUT ====================

@Client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    try:
        # force-subscribe gate
        not_joined = await check_fsub(client, message.from_user.id)
        if not_joined:
            return await send_fsub_message(client, message, not_joined)

        await database.save_user(message.from_user.id)  # keeps the broadcast list complete
        await log_new_user(client, message.from_user)
        await message.reply_photo(photo=START_IMAGE, caption=ui.finish(ui.START_TEXT),
                                  parse_mode=HTML, reply_markup=ui.start_buttons())
    except Exception as e:
        logger.error(f"Start error: {e}")
        try:
            await send(message, ui.START_TEXT, ui.start_buttons())
        except Exception:
            pass


@Client.on_callback_query(filters.regex("^fsub_verify$"))
async def fsub_verify(client, callback_query):
    await fsub_verify_callback(client, callback_query)


@Client.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    text, markup = ui.guide_home(await is_staff(message.from_user.id))
    await send(message, text, markup)


@Client.on_message(filters.command("about") & filters.private)
async def about_command(client, message):
    await send(message, ui.ABOUT_TEXT, ui.about_buttons())


@Client.on_callback_query(filters.regex(r"^help:(.+)$"))
async def cb_help(client, callback_query):
    topic = callback_query.matches[0].group(1)
    staff = await is_staff(callback_query.from_user.id)
    text, markup = ui.guide_home(staff) if topic == "home" else ui.guide_page(topic, staff)
    await callback_query.answer()
    await edit(callback_query.message, text, markup)


@Client.on_callback_query(filters.regex(r"^go:(.+)$"))
async def cb_go(client, callback_query):
    """Shortcuts on the start screen (a photo can't be edited into text, so these open a new message)."""
    where = callback_query.matches[0].group(1)
    user_id = callback_query.from_user.id
    msg = callback_query.message

    if where == "settings":
        await callback_query.answer()
        database.set_scope(user_id, None)
        if await database.get_user_targets(user_id):
            text, markup = await _render_scope_picker(client, user_id)
        else:
            text, markup = await _main_menu(client, user_id)
        return await send(msg, text, markup)
    if where == "help":
        await callback_query.answer()
        text, markup = ui.guide_home(await is_staff(user_id))
        return await send(msg, text, markup)
    if where == "about":
        await callback_query.answer()
        return await send(msg, ui.ABOUT_TEXT, ui.about_buttons())
    if where == "login":
        if await check_fsub(client, user_id):
            return await callback_query.answer("Please join the required channels first, then send /start.", show_alert=True)
        await callback_query.answer()
        return await _begin_login(user_id, lambda text: send(msg, text))
    await callback_query.answer()


# ==================== FORWARDING ON / OFF ====================

@Client.on_message(filters.command("off") & filters.private)
async def cmd_off(client, message: Message):
    await database.set_forwarding(message.from_user.id, False)
    label = await _scope_label(client, message.from_user.id)
    await send(message, note("off", "Forwarding paused",
                             f"{kv('Scope', esc(label))}\nResume anytime with /on."))


@Client.on_message(filters.command(["on", "resume"]) & filters.private)
async def cmd_on(client, message: Message):
    await database.set_forwarding(message.from_user.id, True)
    label = await _scope_label(client, message.from_user.id)
    await send(message, note("on", "Forwarding resumed",
                             f"{kv('Scope', esc(label))}\nNew messages will be forwarded again."))


# ==================== STATUS ====================

async def _build_status_text(user_id: int) -> str:
    s        = await database.get_all_settings(user_id)
    mappings = await database.get_user_mappings(user_id)
    count    = await database.get_forward_count(user_id)

    from SilentXForward.forward import active_userbots
    ub = active_userbots.get(user_id)
    connected = bool(ub and ub.is_connected)

    footer = s.get("endtext")
    overview = quote("\n".join([
        kv("Scope", esc(await _scope_label(None, user_id))),
        kv("Account", ui.state(connected, "Connected", "Not logged in")),
        kv("Forwarding", ui.state(s.get("forwarding_enabled", True), "Active", "Paused")),
        kv("Delay", fmt_delay(s.get("delay", 0.1))),
        kv("Forwarded", f"{count:,} messages"),
        kv("Routes", f"{len(mappings)} source(s)"),
    ]))
    rules = quote("\n".join([
        kv("Whitelist", len(s.get("filters", []))) + "  ·  " + kv("Blacklist", len(s.get("blacklist", []))),
        kv("Replace", len(s.get("replacements", []))) + "  ·  " + kv("Remove", len(s.get("remove_words", []))),
        kv("Caption", "Set" if s.get("caption_template") else "Default"),
        kv("Footer", code(ui.trim(footer, 40)) if footer else "Not set"),
    ]))
    return screen("📊", "Status", overview, "<b>Rules</b>\n" + rules)


@Client.on_message(filters.command("status") & filters.private)
async def cmd_status(client, message: Message):
    await send(message, await _build_status_text(message.from_user.id))


# ==================== DELAY ====================

@Client.on_message(filters.command("setdelay") & filters.private)
async def cmd_setdelay(client, message: Message):
    if len(message.command) < 2:
        return await send(message, usage("/setdelay 2", "Pause between forwarded messages, from 0 to 60 seconds."))
    try:
        delay = float(message.command[1])
        if delay < 0 or delay > 60:
            raise ValueError
    except ValueError:
        return await send(message, note("err", "Invalid value", "Send a number between 0 and 60."))
    await database.set_delay(message.from_user.id, delay)
    label = await _scope_label(client, message.from_user.id)
    await send(message, note("ok", "Delay updated", f"{kv('Delay', fmt_delay(delay))}\n{kv('Scope', esc(label))}"))


# ==================== SKIP (clear pending buffers) ====================

@Client.on_message(filters.command("skip") & filters.private)
async def cmd_skip(client, message: Message):
    from SilentXForward.forward import message_buffer, buffer_tasks
    cleared = 0
    for cid in list(message_buffer.keys()):
        message_buffer[cid].clear()
        cleared += 1
        t = buffer_tasks.get(cid)
        if t and not t.done():
            t.cancel()
    await send(message, note("ok", "Queue cleared", f"{cleared} pending buffer(s) removed."))


# ==================== RULE-COMMAND HELPERS ====================
# whitelist / blacklist / replace / remove-words all share the same shapes.

async def _add_word(message, fn, command: str, what: str, label: str):
    if len(message.command) < 2:
        return await send(message, usage(f"/{command} word", what))
    word = " ".join(message.command[1:]).lower().strip()
    if await fn(message.from_user.id, word):
        await send(message, note("ok", f"{label} added", code(word)))
    else:
        await send(message, note("warn", "Already in the list", code(word)))


async def _remove_word(message, fn, command: str, label: str):
    if len(message.command) < 2:
        return await send(message, usage(f"/{command} word", f"Removes a word from the {label.lower()}."))
    word = " ".join(message.command[1:]).lower().strip()
    if await fn(message.from_user.id, word):
        await send(message, note("ok", f"{label} removed", code(word)))
    else:
        await send(message, note("warn", "Not found", code(word)))


async def _show_list(message, items, icon: str, title: str, empty_title: str, empty_hint: str):
    if not items:
        return await send(message, note("info", empty_title, empty_hint))
    await send_long(message, screen(icon, title, numbered(items), hint=f"{len(items)} item(s)"))


# ==================== WHITELIST ====================

_WHITELIST_WHAT = "Only messages containing this word will be forwarded."

@Client.on_message(filters.command("addfilter") & filters.private)
async def cmd_addfilter(client, message: Message):
    await _add_word(message, database.add_filter, "addfilter", _WHITELIST_WHAT, "Whitelist word")

@Client.on_message(filters.command("whitelist") & filters.private)
async def cmd_whitelist(client, message: Message):
    await _add_word(message, database.add_filter, "whitelist", _WHITELIST_WHAT, "Whitelist word")

@Client.on_message(filters.command("remfilter") & filters.private)
async def cmd_remfilter(client, message: Message):
    await _remove_word(message, database.remove_filter, "remfilter", "Whitelist word")

@Client.on_message(filters.command("remove_whitelist") & filters.private)
async def cmd_remove_whitelist(client, message: Message):
    await _remove_word(message, database.remove_filter, "remove_whitelist", "Whitelist word")

@Client.on_message(filters.command("listfilters") & filters.private)
async def cmd_listfilters(client, message: Message):
    await _show_list(message, await database.get_filters(message.from_user.id), "🔍", "Whitelist",
                     "No whitelist words", "Add one with /addfilter word.")


# ==================== BLACKLIST ====================

@Client.on_message(filters.command("blacklist") & filters.private)
async def cmd_blacklist(client, message: Message):
    await _add_word(message, database.add_blacklist_word, "blacklist",
                    "Messages containing this word will be skipped.", "Blacklist word")

@Client.on_message(filters.command("remove_blacklist") & filters.private)
async def cmd_remove_blacklist(client, message: Message):
    await _remove_word(message, database.remove_blacklist_word, "remove_blacklist", "Blacklist word")

@Client.on_message(filters.command("listblacklist") & filters.private)
async def cmd_listblacklist(client, message: Message):
    await _show_list(message, await database.get_blacklist(message.from_user.id), "🚫", "Blacklist",
                     "No blacklist words", "Add one with /blacklist word.")


# ==================== FOOTER ====================

@Client.on_message(filters.command("endtext") & filters.private)
async def cmd_endtext(client, message: Message):
    if len(message.command) < 2:
        return await send(message, usage("/endtext your footer text", "Text added at the end of every forwarded caption."))
    text = message.text.split(None, 1)[1]
    await database.set_endtext(message.from_user.id, text)
    await send(message, note("ok", "Footer saved", code(text)))

@Client.on_message(filters.command("remendtext") & filters.private)
async def cmd_remendtext(client, message: Message):
    await database.remove_endtext(message.from_user.id)
    await send(message, note("ok", "Footer removed"))

@Client.on_message(filters.command("listendtext") & filters.private)
async def cmd_listendtext(client, message: Message):
    endtext = await database.get_endtext(message.from_user.id)
    if not endtext:
        return await send(message, note("info", "No footer set", "Add one with /endtext text."))
    await send(message, screen("✍️", "Footer", code(endtext)))


# ==================== CAPTION TEMPLATE ====================

CAPTION_VARS_TEXT = ui.CAPTION_VARS_TEXT


@Client.on_message(filters.command("setcaption") & filters.private)
async def cmd_setcaption(client, message: Message):
    if len(message.command) < 2:
        return await send(message, CAPTION_VARS_TEXT)
    template = message.text.split(None, 1)[1]
    await database.set_caption_template(message.from_user.id, template)
    await send(message, note("ok", "Caption template saved", code(template) + "\n\nForwarded messages will now use this caption."))

@Client.on_message(filters.command("showcaption") & filters.private)
async def cmd_showcaption(client, message: Message):
    template = await database.get_caption_template(message.from_user.id)
    if not template:
        return await send(message, note("info", "No caption template", "The original caption is used. Add one with /setcaption."))
    await send(message, screen("📝", "Caption Template", code(template)))

@Client.on_message(filters.command("delcaption") & filters.private)
async def cmd_delcaption(client, message: Message):
    await database.remove_caption_template(message.from_user.id)
    await send(message, note("ok", "Caption template removed", "The original caption is used again."))


# ==================== REPLACE WORDS ====================

@Client.on_message(filters.command("addreplace") & filters.private)
async def cmd_addreplace(client, message: Message):
    if len(message.command) < 2:
        return await send(message, usage("/addreplace Old:New | Old2:New2",
                                         "Replaces words in captions. Separate several rules with |.",
                                         "/addreplace Day:Night | You:Me"))
    raw = message.text.split(None, 1)[1]
    rules, bad = [], []
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            bad.append(part)
            continue
        old, new = part.split(":", 1)
        rules.append((old.strip(), new.strip()))
    if not rules:
        return await send(message, note("err", "Invalid format", "Use " + code("Old:New | Old2:New2")))
    added = await database.add_replacements(message.from_user.id, rules)
    detail = f"{len(rules)} rule(s) processed · {added} new"
    if bad:
        detail += f"\n⚠️ Skipped (missing “:”): {code(' | '.join(bad))}"
    await send(message, note("ok", "Replace rules saved", detail))

@Client.on_message(filters.command("remreplace") & filters.private)
async def cmd_remreplace(client, message: Message):
    if len(message.command) < 2:
        return await send(message, usage("/remreplace Old | Old2", "Removes the replace rules for these words."))
    olds = [w.strip() for w in message.text.split(None, 1)[1].split("|") if w.strip()]
    removed = await database.remove_replacements(message.from_user.id, olds)
    if removed:
        await send(message, note("ok", "Replace rules removed", f"{removed} rule(s) deleted."))
    else:
        await send(message, note("warn", "No matching rule found"))

@Client.on_message(filters.command("listreplace") & filters.private)
async def cmd_listreplace(client, message: Message):
    rules = await database.get_replacements(message.from_user.id)
    if not rules:
        return await send(message, note("info", "No replace rules", "Add one with /addreplace Old:New."))
    body = "\n".join(f"{i}. {code(o)} → {code(n)}" for i, (o, n) in enumerate(rules, 1))
    await send_long(message, screen("🔁", "Replace Rules", body, hint=f"{len(rules)} rule(s)"))

@Client.on_message(filters.command("clearreplace") & filters.private)
async def cmd_clearreplace(client, message: Message):
    await database.clear_replacements(message.from_user.id)
    await send(message, note("ok", "Replace rules cleared"))


# ==================== REMOVE WORDS ====================

@Client.on_message(filters.command("addremoveword") & filters.private)
async def cmd_addremoveword(client, message: Message):
    if len(message.command) < 2:
        return await send(message, usage("/addremoveword Word1 | Word2",
                                         "These words are stripped from captions. Separate several with |.",
                                         "/addremoveword Hdts | Hdcam"))
    words = [w.strip() for w in message.text.split(None, 1)[1].split("|") if w.strip()]
    if not words:
        return await send(message, note("err", "No valid word found"))
    added = await database.add_remove_words(message.from_user.id, words)
    await send(message, note("ok", "Remove-words saved", f"{added} new word(s) added."))

@Client.on_message(filters.command("remremoveword") & filters.private)
async def cmd_remremoveword(client, message: Message):
    if len(message.command) < 2:
        return await send(message, usage("/remremoveword Word1 | Word2", "Stops removing these words."))
    words = [w.strip() for w in message.text.split(None, 1)[1].split("|") if w.strip()]
    removed = await database.remove_remove_words(message.from_user.id, words)
    if removed:
        await send(message, note("ok", "Remove-words updated", f"{removed} word(s) deleted."))
    else:
        await send(message, note("warn", "No matching word found"))

@Client.on_message(filters.command("listremovewords") & filters.private)
async def cmd_listremovewords(client, message: Message):
    await _show_list(message, await database.get_remove_words(message.from_user.id), "🧹", "Remove Words",
                     "No remove-words", "Add some with /addremoveword Word.")

@Client.on_message(filters.command("clearremovewords") & filters.private)
async def cmd_clearremovewords(client, message: Message):
    await database.clear_remove_words(message.from_user.id)
    await send(message, note("ok", "Remove-words cleared"))


# ==================== RESET EVERYTHING (danger zone) ====================
# Nothing is deleted without the confirmation button.

RESET_WARN_TEXT = ui.RESET_WARN_TEXT


def _reset_confirm_markup(user_id: int):
    return kb(
        [btn("⚠️ Yes, Reset Everything", f"confirm_reset:{user_id}")],
        [btn("Cancel", f"cancel_reset:{user_id}")],
    )


@Client.on_message(filters.command("reset") & filters.private)
async def cmd_reset(client, message: Message):
    await send(message, RESET_WARN_TEXT, _reset_confirm_markup(message.from_user.id))


@Client.on_callback_query(filters.regex(r"^confirm_reset:(\d+)$"))
async def cb_confirm_reset(client, callback_query):
    target_uid = int(callback_query.matches[0].group(1))
    if callback_query.from_user.id != target_uid:
        return await callback_query.answer("This button is not for you.", show_alert=True)

    await database.reset_all_settings(target_uid)
    await callback_query.answer("Reset complete")
    await edit(callback_query.message, note(
        "ok", "Everything was reset",
        "Settings, per-channel settings and all routes are deleted.\nStart again with /set."))


@Client.on_callback_query(filters.regex(r"^cancel_reset:(\d+)$"))
async def cb_cancel_reset(client, callback_query):
    target_uid = int(callback_query.matches[0].group(1))
    if callback_query.from_user.id != target_uid:
        return await callback_query.answer("This button is not for you.", show_alert=True)

    await callback_query.answer("Cancelled")
    text, markup = await _main_menu(client, callback_query.from_user.id)
    await edit(callback_query.message, text, markup)


# ==================== STATS ====================

@Client.on_message(filters.command("count") & filters.private)
async def cmd_count(client, message: Message):
    count = await database.get_forward_count(message.from_user.id)
    await send(message, screen("📈", "Forward Statistics", quote(kv("Total forwarded", f"{count:,} messages")),
                               hint="Reset the counter with /resetcount."))


@Client.on_message(filters.command("resetcount") & filters.private)
async def cmd_resetcount(client, message: Message):
    await database.reset_forward_count(message.from_user.id)
    await send(message, note("ok", "Counter reset"))


# ==================== ADMIN SYSTEM ====================

async def _parse_user_id(message, command: str, what: str):
    """Returns the user id, or None after replying with usage / an error."""
    if len(message.command) < 2:
        await send(message, usage(f"/{command} user_id", what))
        return None
    try:
        return int(message.command[1])
    except ValueError:
        await send(message, note("err", "Invalid user ID", "Send a numeric Telegram user ID."))
        return None


async def _stop_userbot(user_id: int):
    from SilentXForward.forward import active_userbots
    ub = active_userbots.pop(user_id, None)
    if ub:
        try:
            await ub.stop()
        except Exception:
            pass


@Client.on_message(filters.command("addadmin") & filters.private)
@owner_only
async def cmd_addadmin(client, message: Message):
    target_id = await _parse_user_id(message, "addadmin", "Gives a user admin rights (owner only).")
    if target_id is None:
        return
    await database.add_admin(message.from_user.id, target_id)
    await send(message, note("ok", "Admin added", code(target_id)))


@Client.on_message(filters.command("removeuser") & filters.private)
@owner_only
async def cmd_removeuser(client, message: Message):
    target_id = await _parse_user_id(message, "removeuser", "Removes admin rights from a user (owner only).")
    if target_id is None:
        return
    if await database.remove_admin(message.from_user.id, target_id):
        await send(message, note("ok", "Admin removed", code(target_id)))
    else:
        await send(message, note("warn", "Not an admin", code(target_id)))


@Client.on_message(filters.command("ban") & filters.private)
@admin_only
async def cmd_ban(client, message: Message):
    target_id = await _parse_user_id(message, "ban", "Blocks a user from using the bot.")
    if target_id is None:
        return
    if cfg.OWNER_ID and target_id == cfg.OWNER_ID:
        return await send(message, note("err", "Not allowed", "The owner cannot be banned."))
    # always stored under OWNER_ID so the owner and every admin see the same ban list
    await database.ban_user(cfg.OWNER_ID, target_id)
    await _stop_userbot(target_id)
    await send(message, note("stop", "User banned", code(target_id)))


@Client.on_message(filters.command("unban") & filters.private)
@admin_only
async def cmd_unban(client, message: Message):
    target_id = await _parse_user_id(message, "unban", "Lets a banned user use the bot again.")
    if target_id is None:
        return
    if await database.unban_user(cfg.OWNER_ID, target_id):
        await send(message, note("ok", "User unbanned", code(target_id)))
    else:
        await send(message, note("warn", "User is not banned", code(target_id)))


# ==================== ROUTES (source → target) ====================

@Client.on_message(filters.command("set") & filters.private)
async def set_channels(client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 3:
        return await send(message, usage("/set source target",
                                         "Forward everything from the source to the target. Use IDs or @usernames.",
                                         "/set -1001234567890 -1009876543210"))
    proc_msg = await send(message, note("info", "Linking channels…"))
    try:
        source_chat = await smart_get_chat(client, message.command[1], user_id)
        target_chat = await smart_get_chat(client, message.command[2], user_id)
        result = await database.add_target_to_source(
            user_id, source_chat.id, target_chat.id, chat_display_name(source_chat), chat_display_name(target_chat)
        )
        await try_delete(proc_msg)
        if result in ("created", "added"):
            await send(message, screen(
                "✅", "Route created",
                f"📥 <b>Source</b>\n{esc(chat_display_name(source_chat))}\n{code(source_chat.id)}",
                f"📤 <b>Target</b>\n{esc(chat_display_name(target_chat))}\n{code(target_chat.id)}",
                hint="New messages from the source will be forwarded to the target.",
            ))
            await log_source_added(client, message.from_user,
                                   chat_display_name(source_chat), source_chat.id,
                                   chat_display_name(target_chat), target_chat.id)
        else:
            await send(message, note("warn", "Route already exists"))
    except PeerIdInvalid:
        await try_delete(proc_msg)
        await send(message, note(
            "err", "Channel not accessible",
            "Open both channels once in your Telegram app (with the logged-in account), then try /set again."))
    except Exception as e:
        await try_delete(proc_msg)
        await send(message, note("err", "Could not create the route", f"{code(e)}\n\nCheck your connection with /session."))


@Client.on_message(filters.command("remove_target") & filters.private)
async def remove_target_channel(client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 3:
        return await send(message, usage("/remove_target source target", "Unlinks one target from a source."))
    try:
        source_chat = await smart_get_chat(client, message.command[1], user_id)
        target_chat = await smart_get_chat(client, message.command[2], user_id)
        result = await database.remove_target_from_source(user_id, source_chat.id, target_chat.id)
        if result == "removed":
            await send(message, note(
                "ok", "Target removed",
                f"📥 {esc(chat_display_name(source_chat))} {code(source_chat.id)}\n"
                f"📤 {esc(chat_display_name(target_chat))} {code(target_chat.id)}"))
            await log_target_removed(client, message.from_user,
                                     chat_display_name(source_chat), source_chat.id,
                                     chat_display_name(target_chat), target_chat.id)
        else:
            await send(message, note("warn", "Route not found"))
    except Exception as e:
        await send(message, note("err", "Could not remove the target", code(e)))


@Client.on_message(filters.command("remove_source") & filters.private)
async def remove_channel(client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        return await send(message, usage("/remove_source source", "Removes a source and all its targets."))
    try:
        chat = await smart_get_chat(client, message.command[1], user_id)
        name = chat_display_name(chat)
        if await database.remove_source(user_id, chat.id):
            await send(message, note("ok", "Source removed", f"{esc(name)} {code(chat.id)}"))
            await log_source_removed(client, message.from_user, name, chat.id)
        else:
            await send(message, note("warn", "Source not found"))
    except Exception as e:
        await send(message, note("err", "Could not remove the source", code(e)))


@Client.on_message(filters.command("list") & filters.private)
async def list_mappings(client, message: Message):
    user_id = message.from_user.id
    mappings = await database.get_user_mappings(user_id)
    if not mappings:
        return await send(message, note("info", "No routes yet", "Create one with /set source target."))
    blocks = []
    for idx, mapping in enumerate(mappings, 1):
        source_id = mapping["source_id"]
        target_ids = mapping.get("target_ids", [])
        titles = mapping.get("target_titles") or {}
        try:
            src_name = chat_display_name(await smart_get_chat(client, source_id, user_id))
        except Exception:
            src_name = mapping.get("source_title") or "Unknown source"
        lines = [f"<b>{idx}. 📥 {esc(src_name)}</b>\n    {code(source_id)}"]
        for n, tid in enumerate(target_ids):
            try:
                tname = chat_display_name(await smart_get_chat(client, tid, user_id))
            except Exception:
                tname = titles.get(str(tid)) or "Unknown target"
            branch = "└" if n == len(target_ids) - 1 else "├"
            lines.append(f"    {branch} 📤 {esc(tname)}  {code(tid)}")
        blocks.append("\n".join(lines))
    await send_long(message, screen("🗂", "Routes", "\n\n".join(blocks), hint=f"{len(mappings)} source(s)"))


@Client.on_message(filters.command("clear") & filters.private)
async def clear_all(client, message: Message):
    count = await database.clear_all_mappings(message.from_user.id)
    if count > 0:
        await send(message, note("ok", "Routes cleared", f"{count} source(s) removed."))
    else:
        await send(message, note("info", "Nothing to clear", "You have no routes."))


# ==================== BROADCAST ====================

@Client.on_message(filters.command("broadcast") & filters.private)
@admin_only
async def cmd_broadcast(client, message: Message):
    if not message.reply_to_message and len(message.command) < 2:
        return await send(message, usage("/broadcast your message",
                                         "Sends a message to every bot user. Or reply to any message with /broadcast to send that message."))

    status_msg = await send(message, note("info", "Broadcasting…"))

    # everyone who ever started the bot, plus every userbot-session user
    broadcast_users = set(await database.get_all_user_ids())
    all_sessions = await database.get_all_userbot_sessions()
    broadcast_users.update(doc["user_id"] for doc in all_sessions if doc.get("user_id"))
    user_ids = list(broadcast_users)

    if not user_ids:
        return await edit(status_msg, note("warn", "No users found"))

    success = failed = 0
    for uid in user_ids:
        try:
            if message.reply_to_message:
                await copy_keep_cover(message.reply_to_message, uid)
            else:
                text = message.text.split(None, 1)[1]
                await client.send_message(uid, text, parse_mode=HTML)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)  # flood protection

    await edit(status_msg, screen(
        "📢", "Broadcast complete",
        quote(kv("Delivered", success) + "\n" + kv("Failed", failed) + "\n" + kv("Total", len(user_ids)))))


# ==================== ACCOUNT / LOGIN ====================

async def _begin_login(user_id: int, reply):
    """Start the login flow. `reply` is an async function that sends a message."""
    existing = await database.get_userbot_session(user_id)
    if existing:
        return await reply(screen(
            "✅", "Already connected",
            quote(kv("Phone", code(existing.get("phone", "N/A"))) + "\n" + kv("Since", esc(existing.get("created_at", "N/A")))),
            hint="To switch accounts, use /logout first."))
    login_states[user_id] = {"step": "phone"}
    await reply(screen(
        "🔑", "Connect your account",
        ui.steps(1),
        "Send your <b>phone number</b> with the country code.\n\n"
        "<b>Example</b>\n<code>+919876543210</code>",
        quote("🔒 Your number is only used to sign in. You can stop anytime with /cancel."),
    ))


@Client.on_message(filters.command("login") & filters.private)
async def cmd_login(client, message: Message):
    user_id = message.from_user.id
    not_joined = await check_fsub(client, user_id)
    if not_joined:
        return await send_fsub_message(client, message, not_joined)
    await _begin_login(user_id, lambda text: send(message, text))


@Client.on_message(filters.command("logout") & filters.private)
async def cmd_logout(client, message: Message):
    user_id = message.from_user.id
    from SilentXForward.forward import active_userbots
    ub = active_userbots.get(user_id)
    if ub:
        try:
            await ub.stop()
        except Exception:
            pass
        active_userbots.pop(user_id, None)
    if await database.delete_userbot_session(user_id):
        await log_logout(client, message.from_user)
        await send(message, note("ok", "Logged out", "Your session was removed. You can connect again anytime with /login."))
    else:
        await send(message, note("info", "Not connected", "You are not logged in. Use /login to connect your account."))


async def _session_card(user_id: int):
    session = await database.get_userbot_session(user_id)
    if not session:
        return None
    from SilentXForward.forward import active_userbots
    ub = active_userbots.get(user_id)
    online = bool(ub and ub.is_connected)
    return screen(
        "🔑", "Session",
        quote(kv("Status", ui.state(online, "Connected", "Offline — restart the bot"))
              + "\n" + kv("Phone", code(session.get("phone", "N/A")))
              + "\n" + kv("Since", esc(session.get("created_at", "N/A")))),
        hint="To switch accounts, use /logout first.")


@Client.on_message(filters.command("session") & filters.private)
async def cmd_session(client, message: Message):
    card = await _session_card(message.from_user.id)
    if card is None:
        return await send(message, note("info", "Not connected", "You are not logged in yet. Use /login to connect your account."))
    await send(message, card)


@Client.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(client, message: Message):
    user_id = message.from_user.id
    if user_id in login_states:
        tc = login_states[user_id].get("temp_client")
        if tc:
            try:
                await tc.disconnect()
            except Exception:
                pass
        del login_states[user_id]
        await send(message, note("ok", "Login cancelled"))
    else:
        await send(message, note("info", "Nothing to cancel", "No login is in progress."))


# ==================== LOGIN STEP HANDLER ====================

_LOGIN_DONE = screen(
    "🎉", "Account connected",
    "Your session is saved and active.",
    "<b>Next</b>\n"
    "1. Open your source and target channels once in Telegram\n"
    "2. Link them with /set source target\n"
    "3. Fine-tune with /settings",
    hint="View the connection with /session · disconnect with /logout.",
)


@Client.on_message(
    filters.private & filters.text &
    ~filters.command(["login", "logout", "session", "cancel", "start", "help", "about",
                      "set", "remove_target", "remove_source", "list", "clear",
                      "on", "off", "resume", "status", "setdelay", "skip",
                      "addfilter", "remfilter", "listfilters",
                      "endtext", "remendtext", "listendtext",
                      "setcaption", "showcaption", "delcaption",
                      "addreplace", "remreplace", "listreplace", "clearreplace",
                      "addremoveword", "remremoveword", "listremovewords", "clearremovewords",
                      "count", "resetcount", "addadmin", "removeuser", "ban", "unban",
                      "broadcast", "reset", "settings", "manage",
                      "whitelist", "remove_whitelist", "blacklist", "remove_blacklist", "listblacklist",
                      "customfilters"])
)
async def login_step_handler(client, message: Message):
    user_id = message.from_user.id
    if user_id not in login_states:
        # let the next handler (settings input, etc.) have the message
        raise ContinuePropagation

    state = login_states[user_id]
    step = state.get("step")

    # ── Step 1: phone ──────────────────────────────────────────────────────
    if step == "phone":
        phone = message.text.strip()
        msg = await send(message, note("info", "Connecting…", "Requesting a verification code."))
        temp_client = Client(f"temp_{user_id}", api_id=cfg.API_ID, api_hash=cfg.API_HASH, in_memory=True)
        try:
            await temp_client.connect()
            sent = await temp_client.send_code(phone)
            state.update({"step": "otp", "phone": phone,
                          "phone_code_hash": sent.phone_code_hash, "temp_client": temp_client})
            login_states[user_id] = state
            await edit(msg, screen(
                "📩", "Verification code sent",
                ui.steps(2),
                "Open your Telegram app and copy the code.\n"
                "Send it with spaces between the digits.\n\n"
                "<b>Example</b>\n<code>1 2 3 4 5</code>",
                quote("Spaces stop Telegram from detecting and invalidating the code."),
            ))
        except PhoneNumberInvalid:
            await temp_client.disconnect()
            del login_states[user_id]
            await edit(msg, note("err", "Invalid phone number",
                                 "Send a valid number with the country code, e.g. " + code("+919876543210")
                                 + ".\nStart again with /login."))
        except Exception as e:
            await temp_client.disconnect()
            del login_states[user_id]
            await edit(msg, note("err", "Could not send the code", f"{code(e)}\n\nStart again with /login."))

    # ── Step 2: verification code ─────────────────────────────────────────
    elif step == "otp":
        otp = message.text.strip().replace(" ", "")
        temp_client = state.get("temp_client")
        await try_delete(message)  # keep the code out of the chat history
        try:
            await temp_client.sign_in(state["phone"], state["phone_code_hash"], otp)
            ss = await temp_client.export_session_string()
            await temp_client.disconnect()
            await database.save_userbot_session(user_id, ss, state["phone"])
            del login_states[user_id]
            from SilentXForward.forward import start_single_userbot
            await start_single_userbot(user_id, ss)
            await log_login(client, message.from_user, state["phone"])
            await send(message, _LOGIN_DONE)
        except PhoneCodeInvalid:
            await send(message, note("err", "Wrong code", "Check the code and send it again."))
        except PhoneCodeExpired:
            await temp_client.disconnect()
            del login_states[user_id]
            await send(message, note("err", "Code expired", "Start again with /login."))
        except SessionPasswordNeeded:
            state["step"] = "password"
            login_states[user_id] = state
            await send(message, screen(
                "🔒", "Two-step verification",
                ui.steps(3),
                "Your account has a cloud password. Send it now.",
                quote("Your message is deleted right after it is read."),
            ))
        except Exception as e:
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            del login_states[user_id]
            await send(message, note("err", "Sign-in failed", f"{code(e)}\n\nStart again with /login."))

    # ── Step 3: cloud password (2FA) ──────────────────────────────────────
    elif step == "password":
        temp_client = state.get("temp_client")
        password = message.text.strip()
        await try_delete(message)  # never leave a password in the chat
        try:
            await temp_client.check_password(password)
            ss = await temp_client.export_session_string()
            await temp_client.disconnect()
            await database.save_userbot_session(user_id, ss, state["phone"])
            del login_states[user_id]
            from SilentXForward.forward import start_single_userbot
            await start_single_userbot(user_id, ss)
            await log_login(client, message.from_user, state["phone"])
            await send(message, _LOGIN_DONE)
        except PasswordHashInvalid:
            await send(message, note("err", "Wrong password", "Send the correct password, or /cancel."))
        except Exception as e:
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            del login_states[user_id]
            await send(message, note("err", "Sign-in failed", f"{code(e)}\n\nStart again with /login."))


# ============================================================================
# ==================== INTERACTIVE SETTINGS MENU ====================
# ============================================================================
# /settings → pick a channel (or “All Channels”) → every change you make
# (menu buttons or text commands) applies to that channel only.
# Where text input is needed the bot prompts and waits for the reply
# (settings_states).

settings_states: dict[int, dict] = {}   # user_id -> {"action": ..., "back": ...}

# which sub-menu to return to after an input is received or cancelled
_INPUT_BACK_MENU = {
    "delay": "delay",
    "filter_add": "filters", "filter_rem": "filters",
    "blacklist_add": "filters", "blacklist_rem": "filters",
    "footer_set": "footer",
    "caption_set": "caption",
    "replace_add": "replace", "replace_rem": "replace",
    "remword_add": "removewords", "remword_rem": "removewords",
    "mapping_set": "manage", "mapping_remtarget": "manage", "mapping_remsource": "manage",
    "admin_add": "admin", "admin_ban": "admin", "admin_unban": "admin",
}

INPUT_PROMPTS = ui.INPUT_PROMPTS


# ==================== CHANNEL SCOPE ====================

_title_cache: dict = {}
_SCOPE_PAGE = 20
GLOBAL_LABEL = "🌐 All Channels (default)"


async def _target_names(client, user_id: int, ids: list) -> dict:
    """channel id -> name: saved name first, then a live lookup, else 'Channel <id>'."""
    saved = dict(await database.get_user_targets(user_id))
    out = {}
    for t in ids:
        name = saved.get(t) or _title_cache.get(t)
        if not name and client is not None:
            try:
                from SilentXForward.forward import active_userbots
                ub = active_userbots.get(user_id)
                getter = ub if (ub and ub.is_connected) else client
                name = chat_display_name(await getter.get_chat(t))
            except Exception:
                name = None
        out[t] = name or f"Channel {t}"
        _title_cache[t] = out[t]
    return out


async def _scope_label(client, user_id: int) -> str:
    tid = database.get_scope(user_id)
    if tid is None:
        return GLOBAL_LABEL
    return "📺 " + (await _target_names(client, user_id, [tid]))[tid]


async def _render_scope_picker(client, user_id: int, page: int = 0):
    targets = await database.get_user_targets(user_id)
    own = await database.get_override_targets(user_id)
    names = await _target_names(client, user_id, [t for t, _ in targets])
    current = database.get_scope(user_id)

    rows = [[btn(("✅ " if current is None else "") + GLOBAL_LABEL, "scope:all")]]
    pages = max(1, -(-len(targets) // _SCOPE_PAGE))
    page = max(0, min(page, pages - 1))
    for t, _ in targets[page * _SCOPE_PAGE:(page + 1) * _SCOPE_PAGE]:
        mark = ("✅ " if t == current else "") + ("✏️ " if t in own else "")
        rows.append([btn(ui.trim(f"{mark}{names[t]}", 56), f"scope:{t}", raw=True)])
    if pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(btn("⬅️ Prev", f"scope:page:{page - 1}"))
        nav_row.append(btn(f"{page + 1}/{pages}", "scope:noop"))
        if page < pages - 1:
            nav_row.append(btn("Next ➡️", f"scope:page:{page + 1}"))
        rows.append(nav_row)
    rows.append([btn("✖️ Close", "menu:close")])

    legend = quote(
        "<b>All Channels</b> — default settings, used by every channel that has none of its own.\n"
        "<b>A channel</b> — its own caption, footer, filters and delay. Other channels stay untouched.\n\n"
        "✏️ has its own settings  ·  ✅ selected"
    )
    text = screen("📺", "Channel Settings", "Choose what you want to configure.", legend)
    if not targets:
        text += "\n\n" + note("info", "No target channels yet", "Link a source and a target first with /set.")
    return text, kb(*rows)


async def _sub(user_id: int) -> str:
    """Subtitle for every sub-screen: which channel is being edited."""
    return "Editing: " + await _scope_label(None, user_id)


# ==================== MAIN MENU ====================

async def _main_menu(client, user_id: int):
    """(text, markup) of the main settings screen — a live summary plus the categories."""
    s = await database.get_all_settings(user_id)
    label = await _scope_label(client, user_id)
    fwd_on = s.get("forwarding_enabled", True)
    summary = quote("\n".join([
        kv("Editing", esc(label)),
        kv("Forwarding", ui.state(fwd_on, "On", "Paused")) + "  ·  " + kv("Delay", fmt_delay(s.get("delay", 0.1))),
        kv("Whitelist", len(s.get("filters", []))) + "  ·  " + kv("Blacklist", len(s.get("blacklist", []))),
        kv("Caption", "Set" if s.get("caption_template") else "Default") + "  ·  "
        + kv("Footer", "Set" if s.get("endtext") else "Not set"),
    ]))
    text = screen("⚙️", "Settings", summary, hint="Choose a category below.")

    staff = await is_staff(user_id) or not cfg.OWNER_ID
    last = [btn("🔑 Account", "menu:login")]
    if staff:
        last.append(btn("👑 Admin", "menu:admin"))
    rows = [
        [btn("🔀 Change Channel", "scope:pick")],
        [btn("⏸ Pause Forwarding" if fwd_on else "▶️ Resume Forwarding", "menu:toggle")],
        [btn("⏱ Delay", "menu:delay"), btn("🔍 Filters", "menu:filters")],
        [btn("📝 Caption", "menu:caption"), btn("✍️ Footer", "menu:footer")],
        [btn("🔁 Replace Words", "menu:replace"), btn("🧹 Remove Words", "menu:removewords")],
        [btn("🎛 Content Types", "menu:customfilters"), btn("🗂 Routes", "menu:manage")],
        [btn("📈 Statistics", "menu:stats"), btn("📊 Status", "menu:status")],
        last,
    ]
    if database.get_scope(user_id) is not None:
        rows.append([btn("♻️ Reset This Channel To Default", "scope:reset")])
    rows.append([btn("⚠️ Reset Everything", "menu:reset")])
    rows.append([btn("⬅️ Back", "menu:back"), btn("✖️ Close", "menu:close")])
    return text, kb(*rows)


# ==================== SUB-MENU RENDERERS ====================
# every renderer returns (text, markup)

async def _render_delay(user_id):
    delay = float(await database.get_delay(user_id))
    def label(v):
        return ("✓ " if abs(delay - v) < 1e-9 else "") + f"{v:g} s"
    text = screen("⏱", "Message Delay", quote(kv("Current", fmt_delay(delay))),
                  "The pause between forwarded messages. Pick a preset or send your own value.",
                  subtitle=await _sub(user_id))
    markup = kb(
        [btn(label(0.1), "delay:0.1"), btn(label(0.5), "delay:0.5"), btn(label(1), "delay:1")],
        [btn(label(2), "delay:2"), btn(label(5), "delay:5")],
        [btn("✏️ Custom Value", "input:delay")],
        nav(),
    )
    return text, markup


async def _render_filters(user_id):
    words = await database.get_filters(user_id)
    bl = await database.get_blacklist(user_id)
    white = "<b>Whitelist</b> — only messages containing these words are forwarded\n"
    white += bullets(words) if words else "<i>Empty — every message passes.</i>"
    black = "<b>Blacklist</b> — messages containing these words are skipped\n"
    black += bullets(bl) if bl else "<i>Empty.</i>"
    text = screen("🔍", "Filters", white, black, subtitle=await _sub(user_id))
    markup = kb(
        [btn("➕ Whitelist", "input:filter_add"), btn("➖ Whitelist", "input:filter_rem")],
        [btn("➕ Blacklist", "input:blacklist_add"), btn("➖ Blacklist", "input:blacklist_rem")],
        [btn("🧹 Clear Whitelist", "action:filter_clear"), btn("🧹 Clear Blacklist", "action:blacklist_clear")],
        nav(),
    )
    return text, markup


async def _render_footer(user_id):
    footer = await database.get_endtext(user_id)
    body = code(footer) if footer else "<i>No footer set.</i>"
    text = screen("✍️", "Footer", body, "Text added at the end of every forwarded caption.", subtitle=await _sub(user_id))
    markup = kb([btn("✏️ Set Footer", "input:footer_set"), btn("🗑 Remove", "action:footer_rem")], nav())
    return text, markup


async def _render_caption(user_id):
    tmpl = await database.get_caption_template(user_id)
    body = code(tmpl) if tmpl else "<i>No template — the original caption is used.</i>"
    text = screen("📝", "Caption Template", body, subtitle=await _sub(user_id))
    markup = kb(
        [btn("✏️ Set Template", "input:caption_set"), btn("🗑 Remove", "action:caption_rem")],
        [btn("📚 Variables", "action:caption_vars")],
        nav(),
    )
    return text, markup


async def _render_replace(user_id):
    rules = await database.get_replacements(user_id)
    body = "\n".join(f"{i}. {code(o)} → {code(n)}" for i, (o, n) in enumerate(rules, 1)) if rules else "<i>No rules set.</i>"
    text = screen("🔁", "Replace Words", body, "Words in captions are swapped automatically.", subtitle=await _sub(user_id))
    markup = kb(
        [btn("➕ Add Rule", "input:replace_add"), btn("➖ Remove Rule", "input:replace_rem")],
        [btn("🧹 Clear All", "action:replace_clear")],
        nav(),
    )
    return text, markup


async def _render_removewords(user_id):
    words = await database.get_remove_words(user_id)
    body = bullets(words) if words else "<i>No words set.</i>"
    text = screen("🧹", "Remove Words", body, "These words are stripped from captions.", subtitle=await _sub(user_id))
    markup = kb(
        [btn("➕ Add Words", "input:remword_add"), btn("➖ Remove Words", "input:remword_rem")],
        [btn("🧹 Clear All", "action:remword_clear")],
        nav(),
    )
    return text, markup


async def _render_manage(user_id):
    mappings = await database.get_user_mappings(user_id)
    if mappings:
        body = "\n".join(
            f"{i}. 📥 {esc(ui.trim(m.get('source_title') or m['source_id'], 36))} → {len(m.get('target_ids', []))} target(s)"
            for i, m in enumerate(mappings, 1))
    else:
        body = "<i>No routes yet.</i>"
    text = screen("🗂", "Routes", body, "A route forwards a source channel into one or more targets.")
    markup = kb(
        [btn("➕ Add Route", "input:mapping_set")],
        [btn("➖ Remove Target", "input:mapping_remtarget"), btn("🗑 Remove Source", "input:mapping_remsource")],
        [btn("🧨 Clear All Routes", "action:mapping_clear")],
        nav(),
    )
    return text, markup


async def _render_stats(user_id):
    count = await database.get_forward_count(user_id)
    text = screen("📈", "Statistics", quote(kv("Total forwarded", f"{count:,} messages")))
    markup = kb([btn("🔄 Reset Counter", "action:count_reset")], nav())
    return text, markup


async def _render_login(user_id):
    card = await _session_card(user_id)
    if card:
        return card, kb([btn("🚪 Log Out", "action:logout")], nav())
    text = screen("🔑", "Account", "You are not connected.",
                  "Connecting your account lets the bot read private channels.",
                  hint="For your security the phone number and code are never taken from buttons — send /login.")
    return text, kb(nav())


async def _render_admin(user_id):
    if not (await is_staff(user_id) or not cfg.OWNER_ID):
        return note("stop", "Access denied", "Admin tools are for the owner and admins."), kb(nav())
    text = screen("👑", "Admin Tools", "Manage admins and ban or unban users.")
    markup = kb(
        [btn("➕ Add Admin", "input:admin_add")],
        [btn("🚫 Ban User", "input:admin_ban"), btn("✅ Unban User", "input:admin_unban")],
        nav(),
    )
    return text, markup


async def _render_customfilters(user_id):
    cf = await database.get_content_filters(user_id)
    text = screen(
        "🎛", "Content Types",
        "Choose which kinds of messages are forwarded. ✅ = forwarded, ❌ = skipped.",
        quote("<b>Forward Tag</b>\n✅ keeps the “Forwarded from” header (captions and footers cannot change).\n"
              "❌ sends a clean copy — recommended."),
        subtitle=await _sub(user_id),
    )
    def toggle(key):
        return btn(f"{'✅' if cf.get(key) else '❌'} {ui.CF_LABELS[key]}", f"cf:{key}")
    markup = kb(
        [toggle("forward_tag")],
        [toggle("text"), toggle("document")],
        [toggle("video"), toggle("photo")],
        [toggle("audio"), toggle("sticker")],
        nav(),
    )
    return text, markup


_MENU_RENDERERS = {
    "delay": _render_delay, "filters": _render_filters, "footer": _render_footer,
    "caption": _render_caption, "replace": _render_replace, "removewords": _render_removewords,
    "manage": _render_manage, "stats": _render_stats, "login": _render_login, "admin": _render_admin,
    "customfilters": _render_customfilters,
}


# ==================== COMMANDS THAT OPEN THE MENU ====================

@Client.on_message(filters.command(["settings", "manage"]) & filters.private)
async def cmd_settings_menu(client, message: Message):
    user_id = message.from_user.id
    database.set_scope(user_id, None)  # every /settings starts at the channel picker
    if await database.get_user_targets(user_id):
        text, markup = await _render_scope_picker(client, user_id)
    else:
        text, markup = await _main_menu(client, user_id)
    await send(message, text, markup)


@Client.on_message(filters.command("customfilters") & filters.private)
async def cmd_customfilters(client, message: Message):
    text, markup = await _render_customfilters(message.from_user.id)
    await send(message, text, markup)


# ==================== MENU ROUTER ====================

@Client.on_callback_query(filters.regex(r"^menu:(.+)$"))
async def cb_menu_router(client, callback_query):
    user_id = callback_query.from_user.id
    key = callback_query.matches[0].group(1)
    msg = callback_query.message

    if key == "main":
        await callback_query.answer()
        text, markup = await _main_menu(client, user_id)
        return await edit(msg, text, markup)

    if key == "back":
        await callback_query.answer()
        return await edit(msg, ui.START_TEXT, ui.start_buttons())

    if key == "close":
        await callback_query.answer()
        try:
            await msg.delete()
        except Exception:
            pass
        return

    if key == "toggle":
        enabled = await database.is_forwarding_enabled(user_id)
        await database.set_forwarding(user_id, not enabled)
        await callback_query.answer("Forwarding resumed" if not enabled else "Forwarding paused")
        text, markup = await _main_menu(client, user_id)
        return await edit(msg, text, markup)

    if key == "reset":
        await callback_query.answer()
        return await edit(msg, RESET_WARN_TEXT, _reset_confirm_markup(user_id))

    if key == "status":
        await callback_query.answer()
        return await edit(msg, await _build_status_text(user_id), kb(nav()))

    fn = _MENU_RENDERERS.get(key)
    if fn:
        await callback_query.answer()
        text, markup = await fn(user_id)
        return await edit(msg, text, markup)

    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^scope:(.+)$"))
async def cb_scope(client, callback_query):
    user_id = callback_query.from_user.id
    arg = callback_query.matches[0].group(1)
    msg = callback_query.message

    if arg == "noop":
        return await callback_query.answer()
    if arg == "pick":
        await callback_query.answer()
        return await edit(msg, *await _render_scope_picker(client, user_id))
    if arg.startswith("page:"):
        await callback_query.answer()
        return await edit(msg, *await _render_scope_picker(client, user_id, int(arg.split(":", 1)[1])))
    if arg == "reset":
        tid = database.get_scope(user_id)
        if tid is None:
            return await callback_query.answer("Choose a channel first.", show_alert=True)
        await database.reset_scope(user_id, tid)
        await callback_query.answer("Channel reset to default settings")
        return await edit(msg, *await _main_menu(client, user_id))

    if arg == "all":
        database.set_scope(user_id, None)
        await callback_query.answer("Default settings selected")
    else:
        try:
            tid = int(arg)
        except ValueError:
            return await callback_query.answer()
        if tid not in {t for t, _ in await database.get_user_targets(user_id)}:
            return await callback_query.answer("This channel is no longer in your routes.", show_alert=True)
        database.set_scope(user_id, tid)
        await callback_query.answer("Channel selected")
    await edit(msg, *await _main_menu(client, user_id))


# ==================== DELAY / CONTENT TYPE / ACTIONS ====================

@Client.on_callback_query(filters.regex(r"^delay:(.+)$"))
async def cb_delay_preset(client, callback_query):
    user_id = callback_query.from_user.id
    value = float(callback_query.matches[0].group(1))
    await database.set_delay(user_id, value)
    await callback_query.answer(f"Delay set to {fmt_delay(value)}")
    await edit(callback_query.message, *await _render_delay(user_id))


@Client.on_callback_query(filters.regex(r"^cf:(.+)$"))
async def cb_content_filter_toggle(client, callback_query):
    user_id = callback_query.from_user.id
    key = callback_query.matches[0].group(1)
    try:
        new_val = await database.toggle_content_filter(user_id, key)
    except ValueError:
        return await callback_query.answer("Unknown option")
    await callback_query.answer("Enabled" if new_val else "Disabled")
    await edit(callback_query.message, *await _render_customfilters(user_id))


@Client.on_callback_query(filters.regex(r"^action:(.+)$"))
async def cb_menu_action(client, callback_query):
    user_id = callback_query.from_user.id
    action = callback_query.matches[0].group(1)

    if action == "filter_clear":
        await database.clear_filters(user_id)
        toast, (text, markup) = "Whitelist cleared", await _render_filters(user_id)
    elif action == "blacklist_clear":
        await database.clear_blacklist(user_id)
        toast, (text, markup) = "Blacklist cleared", await _render_filters(user_id)
    elif action == "footer_rem":
        await database.remove_endtext(user_id)
        toast, (text, markup) = "Footer removed", await _render_footer(user_id)
    elif action == "caption_rem":
        await database.remove_caption_template(user_id)
        toast, (text, markup) = "Caption template removed", await _render_caption(user_id)
    elif action == "caption_vars":
        await callback_query.answer()
        return await edit(callback_query.message, ui.CAPTION_VARS_TEXT, kb(nav("caption")))
    elif action == "replace_clear":
        await database.clear_replacements(user_id)
        toast, (text, markup) = "Replace rules cleared", await _render_replace(user_id)
    elif action == "remword_clear":
        await database.clear_remove_words(user_id)
        toast, (text, markup) = "Remove-words cleared", await _render_removewords(user_id)
    elif action == "mapping_clear":
        n = await database.clear_all_mappings(user_id)
        toast, (text, markup) = f"{n} route(s) cleared", await _render_manage(user_id)
    elif action == "count_reset":
        await database.reset_forward_count(user_id)
        toast, (text, markup) = "Counter reset", await _render_stats(user_id)
    elif action == "logout":
        await _stop_userbot(user_id)
        await database.delete_userbot_session(user_id)
        toast, (text, markup) = "Logged out", await _render_login(user_id)
    else:
        return await callback_query.answer()

    await callback_query.answer(toast)
    await edit(callback_query.message, text, markup)


# ==================== TEXT INPUT ====================

@Client.on_callback_query(filters.regex(r"^input:(.+)$"))
async def cb_menu_input_prompt(client, callback_query):
    user_id = callback_query.from_user.id
    key = callback_query.matches[0].group(1)
    prompt = INPUT_PROMPTS.get(key)
    if not prompt:
        return await callback_query.answer()

    settings_states[user_id] = {"action": key, "back": _INPUT_BACK_MENU.get(key, "main")}
    await callback_query.answer()
    text = prompt if key == "caption_set" else screen("✏️", "Input needed", prompt)
    text += "\n\n<i>Send your reply as a message, or tap Cancel.</i>"
    await edit(callback_query.message, text, kb([btn("✖️ Cancel", "input_cancel")]))


@Client.on_callback_query(filters.regex(r"^input_cancel$"))
async def cb_menu_input_cancel(client, callback_query):
    user_id = callback_query.from_user.id
    state = settings_states.pop(user_id, None)
    back_key = state.get("back", "main") if state else "main"
    await callback_query.answer("Cancelled")

    if back_key == "main" or back_key not in _MENU_RENDERERS:
        return await edit(callback_query.message, *await _main_menu(client, user_id))
    await edit(callback_query.message, *await _MENU_RENDERERS[back_key](user_id))


# ── text-input capture (group=2 so it never clashes with the group-0 login handler) ──
@Client.on_message(
    filters.private & filters.text & filters.create(lambda _, __, m: m.from_user.id in settings_states),
    group=2,
)
async def settings_menu_input_handler(client, message: Message):
    user_id = message.from_user.id
    state = settings_states.pop(user_id, None)
    if not state:
        return

    action = state["action"]
    back_key = state.get("back", "main")
    raw = message.text.strip()
    msg = ""

    try:
        if action == "delay":
            val = float(raw)
            if val < 0 or val > 60:
                raise ValueError
            await database.set_delay(user_id, val)
            msg = note("ok", f"Delay set to {fmt_delay(val)}")

        elif action == "filter_add":
            added = await database.add_filter(user_id, raw)
            msg = note("ok", "Whitelist word added") if added else note("warn", "Already in the whitelist")

        elif action == "filter_rem":
            removed = await database.remove_filter(user_id, raw)
            msg = note("ok", "Whitelist word removed") if removed else note("warn", "Word not found")

        elif action == "blacklist_add":
            added = await database.add_blacklist_word(user_id, raw)
            msg = note("ok", "Blacklist word added") if added else note("warn", "Already in the blacklist")

        elif action == "blacklist_rem":
            removed = await database.remove_blacklist_word(user_id, raw)
            msg = note("ok", "Blacklist word removed") if removed else note("warn", "Word not found")

        elif action == "footer_set":
            await database.set_endtext(user_id, raw)
            msg = note("ok", "Footer saved")

        elif action == "caption_set":
            await database.set_caption_template(user_id, raw)
            msg = note("ok", "Caption template saved")

        elif action == "replace_add":
            rules = []
            for part in raw.split("|"):
                part = part.strip()
                if ":" in part:
                    o, n = part.split(":", 1)
                    rules.append((o.strip(), n.strip()))
            if rules:
                added = await database.add_replacements(user_id, rules)
                msg = note("ok", "Replace rules saved", f"{added} new rule(s).")
            else:
                msg = note("err", "Invalid format", "Use " + code("Old:New") + ".")

        elif action == "replace_rem":
            olds = [w.strip() for w in raw.split("|") if w.strip()]
            removed = await database.remove_replacements(user_id, olds)
            msg = note("ok", "Replace rules removed", f"{removed} rule(s) deleted.") if removed else note("warn", "No matching rule")

        elif action == "remword_add":
            words = [w.strip() for w in raw.split("|") if w.strip()]
            added = await database.add_remove_words(user_id, words)
            msg = note("ok", "Remove-words saved", f"{added} new word(s).")

        elif action == "remword_rem":
            words = [w.strip() for w in raw.split("|") if w.strip()]
            removed = await database.remove_remove_words(user_id, words)
            msg = note("ok", "Remove-words updated", f"{removed} word(s) deleted.") if removed else note("warn", "No matching word")

        elif action == "mapping_set":
            parts = raw.split()
            if len(parts) != 2:
                msg = note("err", "Invalid format", "Send source and target separated by a space.")
            else:
                src_chat = await smart_get_chat(client, parts[0], user_id)
                tgt_chat = await smart_get_chat(client, parts[1], user_id)
                result = await database.add_target_to_source(
                    user_id, src_chat.id, tgt_chat.id, chat_display_name(src_chat), chat_display_name(tgt_chat)
                )
                msg = note("ok", "Route created") if result in ("created", "added") else note("warn", "Route already exists")

        elif action == "mapping_remtarget":
            parts = raw.split()
            if len(parts) != 2:
                msg = note("err", "Invalid format", "Send source and target separated by a space.")
            else:
                src_chat = await smart_get_chat(client, parts[0], user_id)
                tgt_chat = await smart_get_chat(client, parts[1], user_id)
                result = await database.remove_target_from_source(user_id, src_chat.id, tgt_chat.id)
                msg = note("ok", "Target removed") if result == "removed" else note("warn", "Route not found")

        elif action == "mapping_remsource":
            src_chat = await smart_get_chat(client, raw, user_id)
            removed = await database.remove_source(user_id, src_chat.id)
            msg = note("ok", "Source removed") if removed else note("warn", "Source not found")

        elif action == "admin_add":
            if cfg.OWNER_ID and user_id != cfg.OWNER_ID:
                msg = note("stop", "Access denied", "Only the owner can add admins.")
            else:
                target = int(raw)
                await database.add_admin(user_id, target)
                msg = note("ok", "Admin added", code(target))

        elif action in ("admin_ban", "admin_unban"):
            if not await is_staff(user_id):
                msg = note("stop", "Access denied", "Only the owner and admins can do this.")
            else:
                target = int(raw)
                if action == "admin_ban":
                    if cfg.OWNER_ID and target == cfg.OWNER_ID:
                        msg = note("err", "Not allowed", "The owner cannot be banned.")
                    else:
                        await database.ban_user(cfg.OWNER_ID, target)
                        await _stop_userbot(target)
                        msg = note("stop", "User banned", code(target))
                else:
                    unbanned = await database.unban_user(cfg.OWNER_ID, target)
                    msg = note("ok", "User unbanned", code(target)) if unbanned else note("warn", "User is not banned")

    except ValueError:
        msg = note("err", "Invalid value", "Please send a valid value.")
    except Exception as e:
        logger.exception("settings_menu_input_handler error")
        msg = note("err", "Something went wrong", code(e))

    if back_key in _MENU_RENDERERS:
        text, markup = await _MENU_RENDERERS[back_key](user_id)
        text = f"{msg}\n\n{text}" if msg else text
    else:
        text, markup = await _main_menu(client, user_id)
        text = f"{msg}\n\n{text}" if msg else text

    await send(message, text, markup)
