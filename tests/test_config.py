from pathlib import Path
import unittest

from musafirs_bot.config import Settings


class ConfigTests(unittest.TestCase):
    def settings(self, sources=(), parents=(1, 2)):
        return Settings(
            collector_token="token",
            publisher_token=None,
            source_chat_ids=frozenset(sources),
            parent_user_ids=frozenset(parents),
            review_chat_id=-100,
            data_dir=Path("data"),
            long_poll_timeout=30,
            manual_scan_seconds=60,
        )

    def test_at_most_ten_sources(self):
        self.settings(range(10)).validate_for_run()
        with self.assertRaisesRegex(ValueError, "at most ten"):
            self.settings(range(11)).validate_for_run()

    def test_at_most_two_parents(self):
        with self.assertRaisesRegex(ValueError, "at most two"):
            self.settings(parents=(1, 2, 3)).validate_for_run()


if __name__ == "__main__":
    unittest.main()
