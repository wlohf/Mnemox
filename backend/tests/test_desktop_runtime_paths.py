import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils import paths


class DesktopRuntimePathsTests(unittest.TestCase):
    def test_mnemox_data_dir_redirects_runtime_data_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "MnemoxData"
            with patch.dict(os.environ, {"MNEMOX_DATA_DIR": str(data_dir)}):
                expected = data_dir.resolve()
                self.assertEqual(paths.get_data_dir(), expected)
                self.assertEqual(paths.get_uploads_dir(), expected / "uploads")
                self.assertEqual(paths.get_images_dir(), expected / "uploads" / "images")
                self.assertEqual(paths.get_chromadb_dir(), expected / "chromadb")

    def test_relative_database_paths_are_resolved_against_runtime_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "MnemoxData"
            with patch.dict(os.environ, {"MNEMOX_DATA_DIR": str(data_dir)}):
                expected = data_dir.resolve()
                self.assertEqual(
                    paths.resolve_runtime_path("study.db"),
                    expected / "study.db",
                )
                self.assertEqual(
                    paths.resolve_runtime_path("uploads/images/1/example.png"),
                    expected / "uploads" / "images" / "1" / "example.png",
                )


if __name__ == "__main__":
    unittest.main()
