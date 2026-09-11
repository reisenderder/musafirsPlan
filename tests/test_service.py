from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from musafirs_bot.config import Settings
from musafirs_bot.database import Database
from musafirs_bot.service import IngestionService


class FakeAPI:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.callbacks = []
        self.download_calls = 0

    def get_file_path(self, file_id):
        return f"documents/{file_id}.pdf"

    def download(self, file_path, max_bytes=None):
        self.download_calls += 1
        return b"same educational file"

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        return {"message_id": len(self.sent)}

    def edit_message(self, chat_id, message_id, text, reply_markup):
        self.edited.append((chat_id, message_id, text, reply_markup))
        return {"message_id": message_id}

    def answer_callback(self, callback_query_id, text, alert=False):
        self.callbacks.append((callback_query_id, text, alert))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        data = Path(self.temp.name)
        self.settings = Settings(
            collector_token="token",
            publisher_token=None,
            source_chat_ids=frozenset({-1001}),
            parent_user_ids=frozenset({11, 22}),
            review_chat_id=-2000,
            data_dir=data,
            long_poll_timeout=1,
            manual_scan_seconds=10,
        )
        self.settings.create_directories()
        self.db = Database(self.settings.database_path)
        self.db.initialize()
        self.api = FakeAPI()
        self.service = IngestionService(self.settings, self.db, self.api)

    def tearDown(self):
        self.temp.cleanup()

    def message(self, message_id=1):
        return {
            "message_id": message_id,
            "chat": {"id": -1001, "type": "supergroup", "title": "Materials"},
            "from": {"id": 5, "first_name": "Teacher", "is_bot": False},
            "document": {
                "file_id": f"file-{message_id}",
                "file_unique_id": f"unique-{message_id}",
                "file_name": "workbook.pdf",
                "mime_type": "application/pdf",
                "file_size": 22,
            },
        }

    def test_allowed_document_is_stored_and_proposed(self):
        item = self.service.process_message(self.message())
        self.assertEqual(item.status, "proposed")
        self.assertTrue(Path(item.local_path).exists())
        self.assertEqual(len(self.api.sent), 1)

    def test_same_file_content_is_deduplicated(self):
        first = self.service.process_message(self.message(1))
        second = self.service.process_message(self.message(2))
        self.assertEqual(first.status, "proposed")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(len(self.api.sent), 1)

    def test_oversized_file_is_registered_without_download(self):
        message = self.message()
        message["document"]["file_size"] = self.settings.max_download_bytes + 1
        item = self.service.process_message(message)
        self.assertEqual(item.status, "proposed")
        self.assertIsNone(item.local_path)
        self.assertEqual(self.api.download_calls, 0)
        self.assertIn("больше 20 МБ", self.api.sent[0][1])

    def test_manual_inbox_is_idempotent(self):
        source = self.settings.manual_inbox / "large.pdf"
        source.write_bytes(b"manual material")
        first = self.service.import_manual_inbox()
        second = self.service.import_manual_inbox()
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertTrue(source.exists())

    def test_manual_executable_is_skipped(self):
        (self.settings.manual_inbox / "unsafe.exe").write_bytes(b"not executed")
        self.assertEqual(self.service.import_manual_inbox(), [])

    def test_outsider_callback_is_denied(self):
        self.service.process_message(self.message())
        self.service.process_update(
            {
                "callback_query": {
                    "id": "callback",
                    "from": {"id": 999, "first_name": "Outsider"},
                    "data": "wp3:take:1",
                }
            }
        )
        self.assertTrue(self.api.callbacks[-1][2])

    def test_parent_conflict_updates_card(self):
        self.service.process_message(self.message())
        for callback_id, parent_id, action in (
            ("a", 11, "take"), ("b", 22, "reject")
        ):
            self.service.process_update(
                {
                    "callback_query": {
                        "id": callback_id,
                        "from": {"id": parent_id, "first_name": str(parent_id)},
                        "data": f"wp3:{action}:1",
                        "message": {"message_id": 1, "chat": {"id": -2000}},
                    }
                }
            )
        self.assertEqual(self.db.get_item(1).status, "conflict")
        self.assertIn("разногласие", self.api.callbacks[-1][1].lower())


if __name__ == "__main__":
    unittest.main()
