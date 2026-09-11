import unittest

from musafirs_bot.storage import safe_file_name


class StorageTests(unittest.TestCase):
    def test_path_segments_are_removed(self):
        self.assertEqual(safe_file_name("../../lesson.pdf"), "lesson.pdf")

    def test_windows_reserved_characters_are_replaced(self):
        self.assertEqual(safe_file_name("lesson:one?.pdf"), "lesson_one_.pdf")


if __name__ == "__main__":
    unittest.main()
