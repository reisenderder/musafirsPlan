from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .models import Candidate, CandidateKind


URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
SUPPORTED_DOCUMENTS = {
    ".pdf", ".doc", ".docx", ".odt", ".ppt", ".pptx", ".odp", ".txt", ".rtf"
}
MIN_TEXT_LENGTH = 80


def _display_name(user: dict[str, Any] | None) -> str:
    if not user:
        return "неизвестный автор"
    full_name = " ".join(
        part for part in (user.get("first_name"), user.get("last_name")) if part
    ).strip()
    return full_name or user.get("username") or str(user.get("id", "неизвестно"))


def _message_link(chat: dict[str, Any], message_id: int | None) -> str | None:
    if not message_id:
        return None
    if chat.get("username"):
        return f"https://t.me/{chat['username']}/{message_id}"
    chat_id = str(chat.get("id", ""))
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    return None


def _source(message: dict[str, Any]) -> tuple[str, str | None, str]:
    chat = message.get("chat", {})
    title = chat.get("title") or chat.get("username") or chat.get("first_name") or str(chat.get("id", ""))
    message_id = message.get("message_id")
    link = _message_link(chat, message_id)

    author_name = _display_name(message.get("from"))
    origin = message.get("forward_origin") or {}
    origin_type = origin.get("type")
    if origin_type == "channel":
        origin_chat = origin.get("chat", {})
        title = origin_chat.get("title") or title
        author_name = str(origin_chat.get("title") or author_name)
        origin_message_id = origin.get("message_id")
        link = _message_link(origin_chat, origin_message_id) or link
    elif origin_type == "user":
        author_name = _display_name(origin.get("sender_user"))
        title = f"Переслано от {author_name}"
    elif origin_type == "hidden_user":
        author_name = str(origin.get("sender_user_name") or "скрытый автор")
        title = f"Переслано от {author_name}"
    elif origin_type == "chat":
        origin_chat = origin.get("sender_chat", {})
        title = str(origin_chat.get("title") or title)
        author_name = str(origin.get("author_signature") or title)
    return str(title), link, author_name


def classify_message(message: dict[str, Any]) -> Candidate | None:
    """Return a normalized candidate, or None for conversational noise."""
    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return None

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None:
        return None

    text = (message.get("caption") or message.get("text") or "").strip()
    source_title, source_link, author_name = _source(message)
    common = dict(
        fingerprint=f"telegram:{chat_id}:{message_id}",
        source_chat_id=int(chat_id),
        source_message_id=int(message_id),
        media_group_id=str(message["media_group_id"]) if message.get("media_group_id") else None,
        source_title=source_title,
        source_link=source_link,
        author_id=int(sender["id"]) if sender.get("id") is not None else None,
        author_name=author_name,
        text=text,
        raw=message,
    )

    document = message.get("document")
    if document:
        file_name = document.get("file_name") or "document"
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_DOCUMENTS:
            return None
        return Candidate(
            kind=CandidateKind.DOCUMENT,
            file_id=document.get("file_id"),
            file_unique_id=document.get("file_unique_id"),
            file_name=file_name,
            mime_type=document.get("mime_type"),
            file_size=document.get("file_size"),
            **common,
        )

    photos = message.get("photo") or []
    if photos:
        photo = max(photos, key=lambda item: item.get("file_size", 0))
        return Candidate(
            kind=CandidateKind.IMAGE,
            file_id=photo.get("file_id"),
            file_unique_id=photo.get("file_unique_id"),
            file_name=f"photo-{message_id}.jpg",
            mime_type="image/jpeg",
            file_size=photo.get("file_size"),
            **common,
        )

    for field in ("video", "audio", "voice"):
        media = message.get(field)
        if media:
            return Candidate(
                kind=CandidateKind.MEDIA,
                file_id=media.get("file_id"),
                file_unique_id=media.get("file_unique_id"),
                file_name=media.get("file_name") or f"{field}-{message_id}",
                mime_type=media.get("mime_type"),
                file_size=media.get("file_size"),
                **common,
            )

    if URL_RE.search(text):
        return Candidate(kind=CandidateKind.LINK, **common)
    if len(text) >= MIN_TEXT_LENGTH:
        return Candidate(kind=CandidateKind.TEXT, **common)
    return None
