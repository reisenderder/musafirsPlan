from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
import time
from typing import Any

from .config import Settings
from .database import Database
from .filtering import classify_message
from .models import Item, ItemStatus, ParentAction
from .review import card_text, details_text, keyboard
from .storage import digest_file, store_download, store_manual
from .telegram_api import TelegramAPI, TelegramError


LOGGER = logging.getLogger("musafirs_bot")
MANUAL_ALLOWED_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".odt", ".ppt", ".pptx", ".odp", ".txt", ".rtf",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp3", ".m4a", ".wav", ".mp4", ".mov",
}


def person_name(user: dict[str, Any]) -> str:
    name = " ".join(
        str(part) for part in (user.get("first_name"), user.get("last_name")) if part
    ).strip()
    return name or str(user.get("username") or user.get("id") or "unknown")


class IngestionService:
    def __init__(self, settings: Settings, database: Database, api: TelegramAPI):
        self.settings = settings
        self.database = database
        self.api = api

    def _message_allowed(self, message: dict[str, Any]) -> bool:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        sender_id = sender.get("id")
        if chat_id in self.settings.source_chat_ids:
            return True
        return (
            sender_id in self.settings.parent_user_ids
            and (chat.get("type") == "private" or chat_id == self.settings.review_chat_id)
        )

    def _download_candidate_file(self, item: Item) -> Item:
        if not item.file_id or item.kind == "media":
            return item
        if item.file_size and item.file_size > self.settings.max_download_bytes:
            return item
        try:
            remote_path = self.api.get_file_path(item.file_id)
            content = self.api.download(remote_path, self.settings.max_download_bytes)
            if len(content) > self.settings.max_download_bytes:
                return item
            digest = sha256(content).hexdigest()
            duplicate = self.database.find_by_sha256(digest, item.id)
            if duplicate:
                return self.database.set_status(
                    item.id,
                    ItemStatus.DUPLICATE,
                    "content_duplicate",
                    details=f"same content as item #{duplicate.id}",
                )
            local_path, digest = store_download(
                content, self.settings.files_dir, item.id, item.file_name
            )
            self.database.attach_file(item.id, local_path, digest)
            return self.database.get_item(item.id) or item
        except TelegramError as exc:
            LOGGER.warning("Could not download item %s: %s", item.id, exc)
            return self.database.set_status(
                item.id, ItemStatus.ERROR, "download_failed", details=str(exc)
            )

    def _publish_review(self, item: Item) -> Item:
        if self.settings.review_chat_id is None:
            raise ValueError("Review chat is not configured")
        proposed = self.database.set_status(item.id, ItemStatus.PROPOSED, "review_proposed")
        sent = self.api.send_message(
            self.settings.review_chat_id,
            card_text(proposed, self.settings.max_download_bytes),
            keyboard(proposed.id),
        )
        self.database.set_review_message(
            proposed.id, self.settings.review_chat_id, int(sent["message_id"])
        )
        return self.database.get_item(proposed.id) or proposed

    def process_message(self, message: dict[str, Any]) -> Item | None:
        if not self._message_allowed(message):
            LOGGER.info("Ignored message from a chat or sender outside the allowlist")
            return None
        candidate = classify_message(message)
        if not candidate:
            return None
        item, created = self.database.add_candidate(candidate)
        if not created:
            LOGGER.info("Skipped repeated Telegram message for item %s", item.id)
            return item
        item = self._download_candidate_file(item)
        if item.status == ItemStatus.DUPLICATE.value:
            return item
        return self._publish_review(item)

    def _handle_callback(self, query: dict[str, Any]) -> None:
        callback_id = str(query.get("id", ""))
        sender = query.get("from") or {}
        sender_id = sender.get("id")
        if sender_id not in self.settings.parent_user_ids:
            self.api.answer_callback(callback_id, "Доступ разрешён только родителям.", alert=True)
            return
        data = str(query.get("data", ""))
        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "wp3":
            self.api.answer_callback(callback_id, "Неизвестная команда.", alert=True)
            return
        try:
            action = ParentAction(parts[1])
            item_id = int(parts[2])
        except (ValueError, TypeError):
            self.api.answer_callback(callback_id, "Некорректная команда.", alert=True)
            return

        try:
            item = self.database.apply_parent_action(
                item_id, int(sender_id), person_name(sender), action
            )
        except KeyError:
            self.api.answer_callback(callback_id, "Материал не найден.", alert=True)
            return

        if action == ParentAction.DETAILS:
            if self.settings.review_chat_id is not None:
                self.api.send_message(self.settings.review_chat_id, details_text(item))
            self.api.answer_callback(callback_id, "Подробности опубликованы.")
            return

        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id") or item.review_chat_id
        message_id = message.get("message_id") or item.review_message_id
        if chat_id and message_id:
            try:
                self.api.edit_message(
                    int(chat_id), int(message_id),
                    card_text(item, self.settings.max_download_bytes), keyboard(item.id),
                )
            except TelegramError as exc:
                if "message is not modified" not in str(exc).lower():
                    raise
        response = "Решение сохранено."
        if item.status == ItemStatus.CONFLICT.value:
            response = "Есть разногласие: требуется совместное решение."
        self.api.answer_callback(callback_id, response)

    def process_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return
        message = update.get("message") or update.get("channel_post")
        if message:
            self.process_message(message)

    def import_manual_inbox(self) -> list[Item]:
        imported: list[Item] = []
        for path in sorted(self.settings.manual_inbox.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in MANUAL_ALLOWED_SUFFIXES:
                LOGGER.warning("Skipped unsupported manual file type: %s", path.name)
                continue
            digest = digest_file(path)
            item, created = self.database.add_manual_candidate(path, f"manual:{digest}")
            if not created:
                continue
            duplicate = self.database.find_by_sha256(digest, item.id)
            if duplicate:
                self.database.set_status(
                    item.id,
                    ItemStatus.DUPLICATE,
                    "content_duplicate",
                    details=f"same content as item #{duplicate.id}",
                )
                continue
            local_path, stored_digest = store_manual(path, self.settings.files_dir, item.id)
            self.database.attach_file(item.id, local_path, stored_digest)
            item = self.database.get_item(item.id) or item
            imported.append(self._publish_review(item))
        return imported

    def retry_unpublished(self) -> int:
        """Publish queued candidates whose review card was not sent yet."""
        count = 0
        for status in (ItemStatus.FOUND.value, ItemStatus.ERROR.value, ItemStatus.PROPOSED.value):
            for item in self.database.list_items(status=status, limit=200):
                if item.review_message_id is not None:
                    continue
                self._publish_review(item)
                count += 1
        return count

    def run_forever(self) -> None:
        offset = int(self.database.get_state("telegram_offset", "0") or 0)
        last_manual_scan = 0.0
        LOGGER.info("Collector started; waiting for Telegram updates")
        while True:
            try:
                self.retry_unpublished()
                updates = self.api.get_updates(offset, self.settings.long_poll_timeout)
                for update in updates:
                    update_id = int(update["update_id"])
                    try:
                        self.process_update(update)
                    except Exception:
                        LOGGER.exception("Update %s failed and was recorded as consumed", update_id)
                    finally:
                        offset = max(offset, update_id + 1)
                        self.database.set_state("telegram_offset", str(offset))
                now = time.monotonic()
                if now - last_manual_scan >= self.settings.manual_scan_seconds:
                    self.import_manual_inbox()
                    last_manual_scan = now
            except TelegramError as exc:
                LOGGER.warning("Telegram is temporarily unavailable: %s", exc)
                time.sleep(5)
