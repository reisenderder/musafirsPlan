from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from .config import Settings, load_env_file
from .database import Database
from .service import IngestionService
from .telegram_api import TelegramAPI, TelegramError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Musafirs Telegram material collector")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="path to local env file")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create local directories and SQLite schema")
    subparsers.add_parser("run", help="start the collector with long polling")
    subparsers.add_parser("doctor", help="validate configuration and Telegram tokens")
    discover = subparsers.add_parser("discover", help="show IDs from pending bot updates")
    discover.add_argument("--timeout", type=int, default=10)
    listing = subparsers.add_parser("list", help="list locally stored queue items")
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=50)
    show = subparsers.add_parser("show", help="show one queue item as JSON")
    show.add_argument("item_id", type=int)
    audit = subparsers.add_parser("audit", help="show the local decision log")
    audit.add_argument("--limit", type=int, default=100)
    subparsers.add_parser("import-manual", help="scan the manual inbox now")
    return parser


def _settings(env_path: Path) -> Settings:
    load_env_file(env_path)
    return Settings.from_environment()


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _discover(settings: Settings, timeout: int) -> int:
    if not settings.collector_token:
        raise ValueError("MUSAFIRS_COLLECTOR_BOT_TOKEN is required for discover")
    api = TelegramAPI(settings.collector_token)
    updates = api.get_updates(0, max(1, min(timeout, 50)))
    rows: list[dict[str, object]] = []
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        query = update.get("callback_query") or {}
        sender = message.get("from") or query.get("from") or {}
        chat = message.get("chat") or (query.get("message") or {}).get("chat") or {}
        rows.append(
            {
                "update_id": update.get("update_id"),
                "user_id": sender.get("id"),
                "user_name": sender.get("username") or sender.get("first_name"),
                "chat_id": chat.get("id"),
                "chat_title": chat.get("title") or chat.get("username") or chat.get("first_name"),
                "chat_type": chat.get("type"),
            }
        )
    _print_json(rows)
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        settings = _settings(args.env)
        if args.command == "discover":
            raise SystemExit(_discover(settings, args.timeout))

        settings.create_directories()
        database = Database(settings.database_path)
        database.initialize()

        if args.command == "init":
            print(f"Initialized local data at {settings.data_dir}")
            return
        if args.command == "list":
            _print_json([item.__dict__ for item in database.list_items(args.status, args.limit)])
            return
        if args.command == "show":
            item = database.get_item(args.item_id)
            if not item:
                raise KeyError(f"Unknown item {args.item_id}")
            _print_json(item.__dict__)
            return
        if args.command == "audit":
            _print_json(database.audit_entries(args.limit))
            return

        settings.validate_for_run()
        api = TelegramAPI(settings.collector_token)
        service = IngestionService(settings, database, api)
        if args.command == "doctor":
            collector = api.get_me()
            result: dict[str, object] = {
                "collector": collector.get("username"),
                "sources": len(settings.source_chat_ids),
                "parents": len(settings.parent_user_ids),
                "review_chat_id": settings.review_chat_id,
                "data_dir": str(settings.data_dir),
            }
            if settings.publisher_token:
                result["publisher"] = TelegramAPI(settings.publisher_token).get_me().get("username")
            else:
                result["publisher"] = "not configured (allowed until WP-006)"
            _print_json(result)
            return
        if args.command == "import-manual":
            imported = service.import_manual_inbox()
            print(f"Imported {len(imported)} new material(s)")
            return
        if args.command == "run":
            service.run_forever()
    except (ValueError, KeyError, TelegramError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
