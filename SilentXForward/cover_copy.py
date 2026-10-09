"""Copy a video message WITHOUT losing its Telegram "video cover".

Why this exists: Pyrofork's Message.copy() / send_cached_media() / send_video(file_id)
all re-send a video by file_id and never attach the cover (the separate photo
shown on the video), so users received the video with the default thumbnail.
Here the raw SendMedia request is built by hand with video_cover and
video_timestamp set. Needs Pyrofork >= 2.3.60 (Telegram layer 201+).
"""
import logging

from pyrogram import raw, types, utils
from pyrogram.file_id import FileType

logger = logging.getLogger(__name__)

# True only when the installed Pyrofork knows Telegram's video_cover field
# (Pyrofork >= 2.3.60). On an older library everything quietly stays as before.
COVER_SUPPORTED = "video_cover" in getattr(raw.types.InputMediaDocument, "__slots__", ())

KEEP = object()  # "use the source message's own reply_markup"


def has_cover(src) -> bool:
    """True if `src` is a video message that carries a cover or start time."""
    video = getattr(src, "video", None)
    if not video:
        return False
    return getattr(video, "cover", None) is not None or bool(getattr(video, "start_timestamp", None))


async def copy_with_cover(src, chat_id, caption=None, reply_markup=KEEP, protect_content=False):
    """Like src.copy(chat_id, ...) but keeps cover + start timestamp.

    caption=None keeps the original caption; reply_markup=KEEP keeps the
    original buttons (pass None for no buttons). Returns the sent Message.
    """
    client = src._client
    video = src.video

    media = utils.get_input_media_from_file_id(video.file_id, FileType.VIDEO)
    if video.cover is not None:
        media.video_cover = utils.get_input_media_from_file_id(video.cover.file_id, FileType.PHOTO).id
    if getattr(video, "start_timestamp", None):
        media.video_timestamp = video.start_timestamp
    if getattr(src, "has_media_spoiler", False):
        media.spoiler = True

    if caption is None:
        caption = src.caption.html if src.caption else ""
    if reply_markup is KEEP:
        reply_markup = src.reply_markup

    r = await client.invoke(
        raw.functions.messages.SendMedia(
            peer=await client.resolve_peer(chat_id),
            media=media,
            random_id=client.rnd_id(),
            noforwards=True if protect_content else None,
            reply_markup=await reply_markup.write(client) if reply_markup else None,
            **await utils.parse_text_entities(client, caption, client.parse_mode, None),
        )
    )
    for i in r.updates:
        if isinstance(i, (raw.types.UpdateNewMessage, raw.types.UpdateNewChannelMessage,
                          raw.types.UpdateNewScheduledMessage)):
            return await types.Message._parse(
                client, i.message,
                {u.id: u for u in r.users}, {c.id: c for c in r.chats},
                is_scheduled=isinstance(i, raw.types.UpdateNewScheduledMessage),
            )


async def copy_keep_cover(src, chat_id, **kw):
    """Drop-in for src.copy(chat_id): keeps the cover when there is one and
    quietly falls back to the normal copy if the cover path fails."""
    if has_cover(src):
        try:
            sent = await copy_with_cover(src, chat_id)
            if sent is not None:
                return sent
        except Exception as e:
            logger.warning(f"[COVER] copy with cover failed, using plain copy: {type(e).__name__}: {e}")
    return await src.copy(chat_id, **kw)
