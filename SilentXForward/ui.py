"""
SilentXForward/ui.py
────────────────────
The whole look & feel of the bot lives here: one set of typography helpers,
one button style, and every static page (start, guide, about, prompts).
Handlers only assemble these pieces, so the bot always speaks with one voice.
(Translating or restyling the bot = editing this file.)

Style rules
  • Every screen:  icon + bold title, a divider, then content.
  • One icon per idea:  ✅ done · ⚠️ attention · ❌ problem · ℹ️ info · ▶️/⏸ state.
  • User-supplied text is always HTML-escaped (esc / code) — it can never break a message.
  • Buttons: one emoji + Title Case, two per row at most, Back / Close at the bottom.
"""
import html

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BRAND = "Prime Forward"
VERSION = "3.1"
DIV = "━━━━━━━━━━━━━━━━━━━━"

LINK_BOT = "https://t.me/Prime_Forwards_Bot"
LINK_CHANNEL = "https://t.me/Mrn_Officialx"
LINK_DEV = "https://t.me/mimam_officialx"
LINK_MAINTAINER = "https://t.me/Dark_of_Danger"

_ICONS = {"ok": "✅", "warn": "⚠️", "err": "❌", "info": "ℹ️", "on": "▶️", "off": "⏸️", "stop": "🚫", "lock": "🔒"}


# ═══════════════════════════ text primitives ═══════════════════════════

def esc(value) -> str:
    """Escape anything that came from a user, a chat title or an exception."""
    return html.escape(str(value), quote=False)


def code(value) -> str:
    return f"<code>{esc(value)}</code>"


def head(icon: str, title: str, subtitle: str = None) -> str:
    out = f"{icon} <b>{esc(title)}</b>"
    if subtitle:
        out += f"\n<i>{esc(subtitle)}</i>"
    return f"{out}\n{DIV}"


def screen(icon: str, title: str, *blocks: str, subtitle: str = None, hint: str = None) -> str:
    """Header + content blocks (blank line between them) + optional italic hint."""
    parts = [head(icon, title, subtitle)]
    parts += [b for b in blocks if b]
    if hint:
        parts.append(f"<i>{esc(hint)}</i>")
    return "\n\n".join(parts)


def note(kind: str, title: str, detail: str = None) -> str:
    """Short result message: ok / warn / err / info / on / off / stop."""
    out = f"{_ICONS[kind]} <b>{esc(title)}</b>"
    if detail:
        out += f"\n{detail}"
    return out


def usage(command: str, what: str, example: str = None) -> str:
    out = f"ℹ️ <b>Usage</b>\n{code(command)}\n\n{what}"
    if example:
        out += f"\n\n<b>Example</b>\n{code(example)}"
    return out


def link(label: str, url: str) -> str:
    return '<a href="' + url + '">' + esc(label) + "</a>"


def kv(label: str, value) -> str:
    return f"<b>{esc(label)}</b> · {value}"


def bullets(items, mono: bool = True) -> str:
    return "\n".join(f"• {code(i) if mono else esc(i)}" for i in items)


def numbered(items, mono: bool = True) -> str:
    return "\n".join(f"{n}. {code(i) if mono else esc(i)}" for n, i in enumerate(items, 1))


def quote(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


def state(on: bool, yes: str = "On", no: str = "Off") -> str:
    return f"🟢 {yes}" if on else f"🔴 {no}"


def steps(current: int, total: int = 3) -> str:
    dots = "".join("●" if i < current else "○" for i in range(total))
    return f"<b>Step {current} of {total}</b>  {dots}"


def trim(text: str, n: int = 60) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


# ═══════════════════════════ buttons ═══════════════════════════

def btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)


def ubtn(label: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, url=url)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows if r])


def nav(back: str = "main", label: str = "⬅️ Back") -> list:
    """Standard bottom row of every sub-screen."""
    return [btn(label, f"menu:{back}"), btn("✖️ Close", "menu:close")]


# ═══════════════════════════ start / about ═══════════════════════════

START_TEXT = (
    f"🎬 <b>{BRAND}</b>\n"
    "<i>Premium auto-forwarding for Telegram channels</i>\n"
    f"{DIV}\n\n"
    "Move content from any channel to yours as a clean copy — no “Forwarded from” tag.\n\n"
    "<b>What you get</b>\n"
    "• Multi-source to multi-target routing\n"
    "• Separate settings for every channel\n"
    "• Captions, footers, filters and word rules\n"
    "• Albums, bulk uploads, duplicate protection\n"
    "• Automatic FloodWait handling and retries\n\n"
    "<b>Quick start</b>\n"
    "<b>1.</b> /login — connect your account\n"
    "<b>2.</b> /set — link a source and a target\n"
    "<b>3.</b> /settings — customize each channel\n\n"
    + quote("Maintained by " + link("Dark of Danger", LINK_MAINTAINER) + "  ·  Created by " + link("Muzaffar", LINK_DEV))
)


def start_buttons() -> InlineKeyboardMarkup:
    return kb(
        [btn("⚙️ Settings", "go:settings"), btn("📖 Guide", "go:help")],
        [btn("🔑 Connect Account", "go:login"), btn("ℹ️ About", "go:about")],
        [ubtn("📢 Updates", LINK_CHANNEL), ubtn("👤 Developer", LINK_DEV)],
    )


ABOUT_TEXT = screen(
    "ℹ️", f"About {BRAND}",
    quote(
        kv("Bot", link(BRAND, LINK_BOT)) + "\n"
        + kv("Created by", link("Muzaffar", LINK_DEV)) + "\n"
        + kv("Maintained by", link("Dark of Danger", LINK_MAINTAINER)) + "\n"
        + kv("Version", VERSION + " · Stable") + "\n"
        + kv("Stack", "Python · Pyrogram · MongoDB")
    ),
    "<b>Capabilities</b>\n"
    "✔ Multi-source → multi-target routing\n"
    "✔ Per-channel settings and pause/resume\n"
    "✔ Whitelist / blacklist, replace and remove words\n"
    "✔ Custom caption templates and footer\n"
    "✔ All media types, albums and video covers\n"
    "✔ Userbot login, admin tools and a log channel",
)


def about_buttons() -> InlineKeyboardMarkup:
    return kb([ubtn("📢 Updates", LINK_CHANNEL), ubtn("👤 Developer", LINK_DEV)],
              [btn("⬅️ Back", "menu:back"), btn("✖️ Close", "menu:close")])


# ═══════════════════════════ guide (/help) ═══════════════════════════

_GUIDE = {
    "start": ("🚀", "Getting Started", (
        "<b>1.</b> /login — connect your Telegram account (needed for private channels)\n"
        "<b>2.</b> /set <code>source target</code> — link two channels (IDs or @usernames)\n"
        "<b>3.</b> /settings — pick a channel and fine-tune it\n"
        "<b>4.</b> /status — see everything at a glance\n\n"
        "<i>Open both channels once in your Telegram app before running /set.</i>")),
    "channels": ("🗂", "Channels", (
        "/set <code>source target</code> — create a route\n"
        "/list — show all routes\n"
        "/remove_target <code>source target</code> — remove one target\n"
        "/remove_source <code>source</code> — remove a source\n"
        "/clear — remove every route")),
    "filters": ("🔍", "Filters", (
        "<b>Whitelist</b> — only messages containing the word are forwarded\n"
        "/addfilter · /whitelist <code>word</code>\n"
        "/remfilter · /remove_whitelist <code>word</code>\n"
        "/listfilters\n\n"
        "<b>Blacklist</b> — messages containing the word are skipped\n"
        "/blacklist <code>word</code>\n"
        "/remove_blacklist <code>word</code>\n"
        "/listblacklist\n\n"
        "<b>Content types</b> — /customfilters (text, video, photo, forward tag…)")),
    "caption": ("📝", "Caption & Footer", (
        "<b>Caption template</b>\n"
        "/setcaption <code>template</code> · /showcaption · /delcaption\n\n"
        "<b>Footer</b>\n"
        "/endtext <code>text</code> · /remendtext · /listendtext\n\n"
        "<i>Tip: /setcaption without text lists every variable.</i>")),
    "words": ("🔁", "Word Rules", (
        "<b>Replace</b>\n"
        "/addreplace <code>Old:New | Old2:New2</code>\n"
        "/remreplace <code>Old</code> · /listreplace · /clearreplace\n\n"
        "<b>Remove</b>\n"
        "/addremoveword <code>Word1 | Word2</code>\n"
        "/remremoveword <code>Word</code> · /listremovewords · /clearremovewords")),
    "control": ("🎛", "Control", (
        "/on · /off — resume or pause forwarding\n"
        "/setdelay <code>seconds</code> — delay between messages\n"
        "/skip — clear pending buffers\n"
        "/status · /count · /resetcount\n"
        "/reset — wipe all settings and routes\n\n"
        "<i>Settings apply to the channel chosen in /settings. "
        "With nothing chosen they apply to every channel.</i>")),
    "account": ("🔑", "Account", (
        "/login — connect your account\n"
        "/session — view the connection\n"
        "/logout — disconnect\n"
        "/cancel — stop a login in progress")),
    "admin": ("👑", "Admin", (
        "/broadcast <code>text</code> — message all users (or reply to a message)\n"
        "/ban · /unban <code>user_id</code>\n"
        "/addadmin · /removeuser <code>user_id</code> — owner only")),
}


def guide_home(staff: bool = False):
    topics = [k for k in _GUIDE if k != "admin" or staff]
    rows, row = [], []
    for k in topics:
        icon, name, _ = _GUIDE[k]
        row.append(btn(f"{icon} {name}", f"help:{k}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("⚙️ Open Settings", "go:settings")])
    rows.append(nav("back"))
    text = screen("📖", "Guide", "Choose a topic to see its commands.",
                  hint="Everything is also available as buttons in /settings.")
    return text, kb(*rows)


def guide_page(topic: str, staff: bool = False):
    if topic not in _GUIDE or (topic == "admin" and not staff):
        return guide_home(staff)
    icon, name, body = _GUIDE[topic]
    return screen(icon, name, body), kb([btn("⬅️ Guide", "help:home"), btn("✖️ Close", "menu:close")])


# ═══════════════════════════ caption variables / prompts ═══════════════════════════

CAPTION_VARS_TEXT = screen(
    "📝", "Caption Template",
    "Build your caption from the variables below.",
    "<b>Variables</b>\n"
    "<code>{file_name}</code> · original file name\n"
    "<code>{default_caption}</code> · original caption\n"
    "<code>{title}</code> · title (before year / season / quality)\n"
    "<code>{file_size}</code> · file size\n"
    "<code>{duration}</code> · video duration\n"
    "<code>{language}</code> · language found in the caption\n"
    "<code>{audio}</code> · audio type (DDP5.1, AAC2.0)\n"
    "<code>{quality}</code> · quality (HDRip, BluRay)\n"
    "<code>{resolution}</code> · resolution (480p, 1080p)\n"
    "<code>{year}</code> · year\n"
    "<code>{season}</code> · season (S01)\n"
    "<code>{episode}</code> · episode (E01)\n"
    "<code>{ott}</code> · platform (NF, AMZN)\n"
    "<code>{lib}</code> · codec (x264, x265)\n"
    "<code>{extension}</code> · file extension\n"
    "<code>{fps}</code> · frame rate\n"
    "<code>{bitrate}</code> · audio bitrate\n"
    "<code>{shortsub}</code> · subtitles (Msub / Esub)\n"
    "<code>{height}</code> · <code>{width}</code> · video size",
    "<b>Example</b>\n<code>/setcaption &lt;b&gt;{title}&lt;/b&gt; [{year}] {resolution}</code>",
)

INPUT_PROMPTS = {
    "delay":             "Send the new delay in seconds (0 – 60).\n\n<b>Example</b>\n<code>0.5</code>",
    "filter_add":        "Send the word to <b>add to the whitelist</b>.\nOnly messages containing it will be forwarded.",
    "filter_rem":        "Send the word to <b>remove from the whitelist</b>.",
    "blacklist_add":     "Send the word to <b>add to the blacklist</b>.\nMessages containing it will be skipped.",
    "blacklist_rem":     "Send the word to <b>remove from the blacklist</b>.",
    "footer_set":        "Send the new <b>footer text</b>.",
    "caption_set":       CAPTION_VARS_TEXT + "\n\n<b>Now send your template.</b>",
    "replace_add":       "Send replace rules as <code>Old:New</code>.\nSeparate several rules with <code>|</code>.\n\n<b>Example</b>\n<code>Day:Night | You:Me</code>",
    "replace_rem":       "Send the <b>old word</b> whose rule should be removed.\nSeparate several with <code>|</code>.",
    "remword_add":       "Send the words to <b>strip from captions</b>.\nSeparate several with <code>|</code>.\n\n<b>Example</b>\n<code>Hdts | Hdcam</code>",
    "remword_rem":       "Send the words to <b>stop removing</b>.\nSeparate several with <code>|</code>.",
    "mapping_set":       "Send the <b>source</b> and the <b>target</b> (ID or @username) separated by a space.\n\n<b>Example</b>\n<code>-1001234567890 -1009876543210</code>",
    "mapping_remtarget": "Send the <b>source</b> and the <b>target</b> to unlink, separated by a space.",
    "mapping_remsource": "Send the <b>source</b> (ID or @username) to remove completely.",
    "admin_add":         "Send the <b>user ID</b> to make an admin.",
    "admin_ban":         "Send the <b>user ID</b> to ban.",
    "admin_unban":       "Send the <b>user ID</b> to unban.",
}

CF_LABELS = {
    "forward_tag": "Forward Tag",
    "text":        "Text",
    "document":    "Documents",
    "video":       "Videos",
    "photo":       "Photos",
    "audio":       "Audio",
    "sticker":     "Stickers",
}

RESET_WARN_TEXT = screen(
    "⚠️", "Reset Everything",
    "This permanently deletes:\n"
    "• caption template and footer\n"
    "• whitelist, blacklist, replace and remove words\n"
    "• every per-channel setting\n"
    "• <b>all source and target routes</b>",
    "<b>This cannot be undone.</b>",
)

ACCESS_DENIED_OWNER = note("stop", "Access denied", "This command is available to the bot owner only.")
ACCESS_DENIED_STAFF = note("stop", "Access denied", "This command is available to the owner and admins only.")
BANNED_TEXT = note("stop", "Access suspended",
                   "Your account is restricted from using this bot.\nIf you think this is a mistake, contact the owner.")
