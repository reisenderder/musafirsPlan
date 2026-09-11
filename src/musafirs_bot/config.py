from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs without overwriting the current environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _ids(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return frozenset()
    try:
        return frozenset(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must contain comma-separated integer IDs") from exc


@dataclass(frozen=True)
class Settings:
    collector_token: str
    publisher_token: str | None
    source_chat_ids: frozenset[int]
    parent_user_ids: frozenset[int]
    review_chat_id: int | None
    data_dir: Path
    long_poll_timeout: int
    manual_scan_seconds: int
    max_download_bytes: int = 20 * 1024 * 1024

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ingestion.sqlite3"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def manual_inbox(self) -> Path:
        return self.data_dir / "inbox" / "manual"

    @classmethod
    def from_environment(cls) -> "Settings":
        review_raw = os.environ.get("MUSAFIRS_REVIEW_CHAT_ID", "").strip()
        return cls(
            collector_token=os.environ.get("MUSAFIRS_COLLECTOR_BOT_TOKEN", "").strip(),
            publisher_token=os.environ.get("MUSAFIRS_PUBLISHER_BOT_TOKEN", "").strip() or None,
            source_chat_ids=_ids("MUSAFIRS_ALLOWED_SOURCE_CHAT_IDS"),
            parent_user_ids=_ids("MUSAFIRS_PARENT_USER_IDS"),
            review_chat_id=int(review_raw) if review_raw else None,
            data_dir=Path(os.environ.get("MUSAFIRS_DATA_DIR", "var/telegram")).expanduser().resolve(),
            long_poll_timeout=int(os.environ.get("MUSAFIRS_LONG_POLL_TIMEOUT", "30")),
            manual_scan_seconds=int(os.environ.get("MUSAFIRS_MANUAL_SCAN_SECONDS", "60")),
        )

    def validate_for_run(self) -> None:
        errors: list[str] = []
        if not self.collector_token:
            errors.append("MUSAFIRS_COLLECTOR_BOT_TOKEN is required")
        if self.review_chat_id is None:
            errors.append("MUSAFIRS_REVIEW_CHAT_ID is required")
        if not self.parent_user_ids:
            errors.append("at least one MUSAFIRS_PARENT_USER_IDS value is required")
        if len(self.parent_user_ids) > 2:
            errors.append("WP-003 allows at most two parent IDs")
        if len(self.source_chat_ids) > 10:
            errors.append("WP-003 allows at most ten source chat IDs")
        if not 1 <= self.long_poll_timeout <= 50:
            errors.append("MUSAFIRS_LONG_POLL_TIMEOUT must be between 1 and 50")
        if self.manual_scan_seconds < 10:
            errors.append("MUSAFIRS_MANUAL_SCAN_SECONDS must be at least 10")
        if errors:
            raise ValueError("; ".join(errors))

    def create_directories(self) -> None:
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.manual_inbox.mkdir(parents=True, exist_ok=True)
