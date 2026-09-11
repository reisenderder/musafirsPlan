import unittest

from musafirs_bot.filtering import classify_message


class FilteringTests(unittest.TestCase):
    def base(self):
        return {
            "message_id": 7,
            "chat": {"id": -1001, "type": "supergroup", "title": "Источник"},
            "from": {"id": 42, "first_name": "Автор", "is_bot": False},
        }

    def test_short_conversation_is_ignored(self):
        message = self.base() | {"text": "Спасибо!"}
        self.assertIsNone(classify_message(message))

    def test_link_is_candidate_even_when_short(self):
        message = self.base() | {"text": "https://example.org/lesson"}
        candidate = classify_message(message)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.kind.value, "link")

    def test_supported_document_is_candidate(self):
        message = self.base() | {
            "caption": "Рабочая тетрадь",
            "document": {
                "file_id": "remote",
                "file_unique_id": "unique",
                "file_name": "lesson.pdf",
                "mime_type": "application/pdf",
                "file_size": 123,
            },
        }
        candidate = classify_message(message)
        self.assertEqual(candidate.kind.value, "document")
        self.assertEqual(candidate.file_name, "lesson.pdf")

    def test_private_supergroup_link_is_preserved(self):
        message = self.base() | {"text": "Материал " * 20}
        candidate = classify_message(message)
        self.assertEqual(candidate.source_link, "https://t.me/c/1/7")

    def test_forwarded_author_is_preserved(self):
        message = self.base() | {
            "text": "Материал " * 20,
            "forward_origin": {
                "type": "user",
                "sender_user": {"id": 9, "first_name": "Исходный автор"},
            },
        }
        candidate = classify_message(message)
        self.assertEqual(candidate.author_name, "Исходный автор")

    def test_executable_document_is_ignored(self):
        message = self.base() | {
            "document": {"file_id": "x", "file_name": "unsafe.exe"}
        }
        self.assertIsNone(classify_message(message))


if __name__ == "__main__":
    unittest.main()
