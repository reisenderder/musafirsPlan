from __future__ import annotations

from .models import Item


STATUS_LABELS = {
    "found": "Найден",
    "proposed": "Предложен",
    "approved": "Одобрен для переработки",
    "rejected": "Не брать",
    "postponed": "Отложен",
    "conflict": "Требует совместного решения",
    "duplicate": "Дубликат",
    "error": "Ошибка",
}

KIND_LABELS = {
    "document": "документ",
    "image": "изображение",
    "text": "текст",
    "link": "ссылка",
    "media": "аудио/видео (только регистрация)",
    "manual": "ручной импорт",
}


def human_size(size: int | None) -> str:
    if size is None:
        return "не указан"
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} {unit}"
        value /= 1024
    return str(size)


def card_text(item: Item, max_download_bytes: int) -> str:
    snippet = " ".join(item.text.split())
    if len(snippet) > 500:
        snippet = snippet[:497] + "..."
    if not snippet:
        snippet = "Описание пока отсутствует; анализ появится в WP-004."
    file_line = item.file_name or "нет отдельного файла"
    large_note = ""
    if item.file_size and item.file_size > max_download_bytes:
        large_note = "\n⚠️ Файл больше 20 МБ: добавьте его в локальную папку ручного импорта."
    elif item.file_id and item.kind != "media" and not item.local_path:
        large_note = "\n⚠️ Локальная копия пока не сохранена; проверьте журнал сервиса."
    link_line = f"\nИсточник: {item.source_link}" if item.source_link else ""
    return (
        f"Материал #{item.id}\n"
        f"Статус: {STATUS_LABELS.get(item.status, item.status)}\n"
        f"Откуда: {item.source_title}\n"
        f"Автор/отправитель: {item.author_name}\n"
        f"Тип: {KIND_LABELS.get(item.kind, item.kind)}\n"
        f"Файл: {file_line} ({human_size(item.file_size)})"
        f"{link_line}\n\n"
        f"Кратко: {snippet}"
        f"{large_note}"
    )


def details_text(item: Item) -> str:
    body = item.text.strip() or "Текстового описания нет."
    if len(body) > 3000:
        body = body[:2997] + "..."
    return (
        f"Подробности материала #{item.id}\n"
        f"MIME: {item.mime_type or 'не указан'}\n"
        f"Telegram file_unique_id: {item.file_unique_id or 'нет'}\n"
        f"Локальная копия: {'сохранена' if item.local_path else 'не сохранена'}\n\n"
        f"{body}"
    )


def keyboard(item_id: int) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Взять в работу", "callback_data": f"wp3:take:{item_id}"},
                {"text": "❌ Не брать", "callback_data": f"wp3:reject:{item_id}"},
            ],
            [
                {"text": "🕒 Отложить", "callback_data": f"wp3:postpone:{item_id}"},
                {"text": "🔎 Подробнее", "callback_data": f"wp3:details:{item_id}"},
            ],
        ]
    }
