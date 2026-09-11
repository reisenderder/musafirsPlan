from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from musafirs_bot.database import Database
from musafirs_bot.models import Candidate, CandidateKind, ItemStatus, ParentAction


def candidate(fingerprint: str = "telegram:1:1") -> Candidate:
    return Candidate(
        fingerprint=fingerprint,
        kind=CandidateKind.TEXT,
        source_chat_id=1,
        source_message_id=1,
        media_group_id=None,
        source_title="source",
        source_link=None,
        author_id=10,
        author_name="author",
        text="A useful educational message " * 5,
    )


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        self.db.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_fingerprint_returns_existing_item(self):
        first, created_first = self.db.add_candidate(candidate())
        second, created_second = self.db.add_candidate(candidate())
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.id, second.id)

    def test_opposite_parent_votes_create_conflict(self):
        item, _ = self.db.add_candidate(candidate())
        approved = self.db.apply_parent_action(item.id, 1, "Parent One", ParentAction.TAKE)
        self.assertEqual(approved.status, ItemStatus.APPROVED.value)
        conflict = self.db.apply_parent_action(item.id, 2, "Parent Two", ParentAction.REJECT)
        self.assertEqual(conflict.status, ItemStatus.CONFLICT.value)

    def test_changed_vote_resolves_conflict(self):
        item, _ = self.db.add_candidate(candidate())
        self.db.apply_parent_action(item.id, 1, "One", ParentAction.TAKE)
        self.db.apply_parent_action(item.id, 2, "Two", ParentAction.REJECT)
        resolved = self.db.apply_parent_action(item.id, 2, "Two", ParentAction.TAKE)
        self.assertEqual(resolved.status, ItemStatus.APPROVED.value)


if __name__ == "__main__":
    unittest.main()
