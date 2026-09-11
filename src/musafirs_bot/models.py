from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ItemStatus(StrEnum):
    FOUND = "found"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTPONED = "postponed"
    CONFLICT = "conflict"
    DUPLICATE = "duplicate"
    ERROR = "error"


class CandidateKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    TEXT = "text"
    LINK = "link"
    MEDIA = "media"
    MANUAL = "manual"


class ParentAction(StrEnum):
    TAKE = "take"
    REJECT = "reject"
    POSTPONE = "postpone"
    DETAILS = "details"


@dataclass(frozen=True)
class Candidate:
    fingerprint: str
    kind: CandidateKind
    source_chat_id: int | None
    source_message_id: int | None
    media_group_id: str | None
    source_title: str
    source_link: str | None
    author_id: int | None
    author_name: str
    text: str
    file_id: str | None = None
    file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class Item:
    id: int
    fingerprint: str
    kind: str
    status: str
    source_chat_id: int | None
    source_message_id: int | None
    source_title: str
    source_link: str | None
    author_id: int | None
    author_name: str
    text: str
    file_id: str | None
    file_unique_id: str | None
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    local_path: str | None
    sha256: str | None
    review_chat_id: int | None
    review_message_id: int | None
    created_at: str
    updated_at: str
