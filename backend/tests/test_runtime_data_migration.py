import tempfile
import unittest
from pathlib import Path
from scripts.migrate_runtime_data import migrate


class RuntimeDataMigrationTests(unittest.TestCase):
    def test_dry_run_copy_verification_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "legacy", Path(tmp) / "durable"
            (source / "uploads").mkdir(parents=True)
            (source / "uploads" / "a.md").write_text("user note")
            (source / "rag_settings.json").write_text("{}")
            self.assertEqual(migrate(source, target), 2)
            self.assertFalse(target.exists())
            self.assertEqual(migrate(source, target, apply=True), 2)
            self.assertEqual((target / "uploads" / "a.md").read_text(), "user note")
            self.assertEqual(migrate(source, target, apply=True), 0)

    def test_conflicting_files_abort_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "legacy", Path(tmp) / "durable"
            source.mkdir(); target.mkdir()
            (source / "a").write_text("source")
            (target / "a").write_text("existing")
            with self.assertRaises(ValueError):
                migrate(source, target, apply=True)
            self.assertEqual((target / "a").read_text(), "existing")
