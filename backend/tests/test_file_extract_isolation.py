import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils.file_extract import extract_text_isolated, run_in_killable_subprocess


class IsolatedExtractionTests(unittest.TestCase):
    def test_timeout_kills_the_child_instead_of_leaking_a_parser(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            run_in_killable_subprocess(time.sleep, (60,), 1.0)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(multiprocessing.active_children(), [])

    def test_child_failure_is_reported_without_hanging(self):
        with self.assertRaisesRegex(RuntimeError, "ValueError"):
            run_in_killable_subprocess(int, ("not a number",), 30)

    def test_docx_is_extracted_in_a_subprocess(self):
        import docx

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.docx"
            document = docx.Document()
            document.add_paragraph("贝叶斯定理")
            document.save(path)

            self.assertEqual(extract_text_isolated(path, 1_000, 30), "贝叶斯定理")

    def test_plain_text_skips_the_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text("# 条件概率", encoding="utf-8")
            with patch("app.utils.file_extract.run_in_killable_subprocess") as spawn:
                self.assertEqual(extract_text_isolated(path, 1_000, 30), "# 条件概率")
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
