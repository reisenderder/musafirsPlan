from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from typing import Iterator

from .models import Candidate, CandidateKind, Item, ItemStatus, ParentAction


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


ITEM_COLUMNS = """
id, fingerprint, kind, status, source_chat_id, source_message_id, source_title,
source_link, author_id, author_name, text, file_id, file_unique_id, file_name,
mime_type, file_size, local_path, sha256, review_chat_id, review_message_id,
created_at, updated_at
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_chat_id INTEGER,
                    source_message_id INTEGER,
                    media_group_id TEXT,
                    source_title TEXT NOT NULL DEFAULT '',
                    source_link TEXT,
                    author_id INTEGER,
                    author_name TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    file_id TEXT,
                    file_unique_id TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    local_path TEXT,
                    sha256 TEXT,
                    review_chat_id INTEGER,
                    review_message_id INTEGER,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
                CREATE INDEX IF NOT EXISTS idx_items_sha256 ON items(sha256);
                CREATE INDEX IF NOT EXISTS idx_items_file_unique_id ON items(file_unique_id);

                CREATE TABLE IF NOT EXISTS parent_votes (
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    parent_id INTEGER NOT NULL,
                    parent_name TEXT NOT NULL,
                    vote TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (item_id, parent_id)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
                    actor_id INTEGER,
                    actor_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT,
                    details TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS service_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _to_item(row: sqlite3.Row | None) -> Item | None:
        return Item(**dict(row)) if row else None

    def add_candidate(self, candidate: Candidate) -> tuple[Item, bool]:
        now = utc_now()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO items (
                        fingerprint, kind, status, source_chat_id, source_message_id,
                        media_group_id, source_title, source_link, author_id, author_name,
                        text, file_id, file_unique_id, file_name, mime_type, file_size,
                        raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.fingerprint, candidate.kind.value, ItemStatus.FOUND.value,
                        candidate.source_chat_id, candidate.source_message_id,
                        candidate.media_group_id, candidate.source_title,
                        candidate.source_link, candidate.author_id, candidate.author_name,
                        candidate.text, candidate.file_id, candidate.file_unique_id,
                        candidate.file_name, candidate.mime_type, candidate.file_size,
                        json.dumps(candidate.raw, ensure_ascii=False) if candidate.raw else None,
                        now, now,
                    ),
                )
                item_id = int(cursor.lastrowid)
                connection.execute(
                    """INSERT INTO audit_log
                    (item_id, actor_id, actor_name, action, old_status, new_status, details, created_at)
                    VALUES (?, NULL, 'system', 'candidate_received', NULL, ?, NULL, ?)""",
                    (item_id, ItemStatus.FOUND.value, now),
                )
                row = connection.execute(
                    f"SELECT {ITEM_COLUMNS} FROM items WHERE id = ?", (item_id,)
                ).fetchone()
                return self._to_item(row), True  # type: ignore[return-value]
            except sqlite3.IntegrityError:
                row = connection.execute(
                    f"SELECT {ITEM_COLUMNS} FROM items WHERE fingerprint = ?",
                    (candidate.fingerprint,),
                ).fetchone()
                return self._to_item(row), False  # type: ignore[return-value]

    def add_manual_candidate(self, path: Path, fingerprint: str) -> tuple[Item, bool]:
        candidate = Candidate(
            fingerprint=fingerprint,
            kind=CandidateKind.MANUAL,
            source_chat_id=None,
            source_message_id=None,
            media_group_id=None,
            source_title="Локальная папка ручного импорта",
            source_link=None,
            author_id=None,
            author_name="local user",
            text="",
            file_name=path.name,
            mime_type=None,
            file_size=path.stat().st_size,
        )
        return self.add_candidate(candidate)

    def get_item(self, item_id: int) -> Item | None:
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT {ITEM_COLUMNS} FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            return self._to_item(row)

    def list_items(self, status: str | None = None, limit: int = 50) -> list[Item]:
        with self.connect() as connection:
            if status:
                rows = connection.execute(
                    f"SELECT {ITEM_COLUMNS} FROM items WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT {ITEM_COLUMNS} FROM items ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._to_item(row) for row in rows]  # type: ignore[misc]

    def find_by_sha256(self, digest: str, exclude_item_id: int) -> Item | None:
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT {ITEM_COLUMNS} FROM items WHERE sha256 = ? AND id != ? ORDER BY id LIMIT 1",
                (digest, exclude_item_id),
            ).fetchone()
            return self._to_item(row)

    def attach_file(self, item_id: int, local_path: Path, digest: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE items SET local_path = ?, sha256 = ?, updated_at = ? WHERE id = ?",
                (str(local_path), digest, now, item_id),
            )

    def set_status(
        self,
        item_id: int,
        status: ItemStatus,
        action: str,
        details: str | None = None,
        actor_id: int | None = None,
        actor_name: str = "system",
    ) -> Item:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown item {item_id}")
            old_status = str(row["status"])
            connection.execute(
                "UPDATE items SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, item_id),
            )
            connection.execute(
                """INSERT INTO audit_log
                (item_id, actor_id, actor_name, action, old_status, new_status, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, actor_id, actor_name, action, old_status, status.value, details, now),
            )
        item = self.get_item(item_id)
        if not item:
            raise KeyError(f"Unknown item {item_id}")
        return item

    def set_review_message(self, item_id: int, chat_id: int, message_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE items SET review_chat_id = ?, review_message_id = ?, updated_at = ? WHERE id = ?",
                (chat_id, message_id, utc_now(), item_id),
            )

    def apply_parent_action(
        self, item_id: int, parent_id: int, parent_name: str, action: ParentAction
    ) -> Item:
        item = self.get_item(item_id)
        if not item:
            raise KeyError(f"Unknown item {item_id}")
        if action == ParentAction.DETAILS:
            return self.set_status(
                item_id, ItemStatus(item.status), "details_requested", actor_id=parent_id,
                actor_name=parent_name,
            )
        if action == ParentAction.POSTPONE:
            return self.set_status(
                item_id, ItemStatus.POSTPONED, action.value, actor_id=parent_id,
                actor_name=parent_name,
            )

        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO parent_votes (item_id, parent_id, parent_name, vote, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id, parent_id) DO UPDATE SET
                    parent_name = excluded.parent_name,
                    vote = excluded.vote,
                    updated_at = excluded.updated_at
                """,
                (item_id, parent_id, parent_name, action.value, now),
            )
            votes = {
                row["vote"]
                for row in connection.execute(
                    "SELECT vote FROM parent_votes WHERE item_id = ?", (item_id,)
                ).fetchall()
            }

        if ParentAction.TAKE.value in votes and ParentAction.REJECT.value in votes:
            status = ItemStatus.CONFLICT
        elif ParentAction.TAKE.value in votes:
            status = ItemStatus.APPROVED
        else:
            status = ItemStatus.REJECTED
        return self.set_status(
            item_id, status, action.value, actor_id=parent_id, actor_name=parent_name
        )

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM service_state WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO service_state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )

    def audit_entries(self, limit: int = 100) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
