from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str, timeout: int = 60):
        if not token:
            raise ValueError("Telegram bot token is empty")
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self.timeout = timeout

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        request = Request(
            f"{self._base}/{method}",
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise TelegramError(f"Telegram request {method} failed: {exc}") from exc
        if not result.get("ok"):
            raise TelegramError(
                f"Telegram request {method} failed: {result.get('description', 'unknown error')}"
            )
        return result.get("result")

    def get_updates(self, offset: int, poll_timeout: int) -> list[dict[str, Any]]:
        result = self.call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": poll_timeout,
                "allowed_updates": ["message", "channel_post", "callback_query"],
            },
        )
        return list(result or [])

    def get_me(self) -> dict[str, Any]:
        return dict(self.call("getMe"))

    def get_file_path(self, file_id: str) -> str:
        result = self.call("getFile", {"file_id": file_id})
        file_path = result.get("file_path")
        if not file_path:
            raise TelegramError("Telegram did not return a file_path")
        return str(file_path)

    def download(self, file_path: str, max_bytes: int | None = None) -> bytes:
        request = Request(f"{self._file_base}/{file_path}", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read(max_bytes + 1 if max_bytes is not None else -1)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise TelegramError(f"Telegram file download failed: {exc}") from exc

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return dict(self.call("sendMessage", payload))

    def edit_message(
        self, chat_id: int, message_id: int, text: str, reply_markup: dict[str, Any]
    ) -> dict[str, Any]:
        return dict(
            self.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "reply_markup": reply_markup,
                },
            )
        )

    def answer_callback(self, callback_query_id: str, text: str, alert: bool = False) -> None:
        self.call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text, "show_alert": alert},
        )
