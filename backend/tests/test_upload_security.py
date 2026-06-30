import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from app.routers.images import MAX_SIZE as IMAGE_MAX_SIZE, _read_limited, _save_image
from app.routers.materials import ALLOWED_CONTENT_TYPES, ALLOWED_EXTENSIONS, MAX_FILE_SIZE

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_upload_file(name: str, content_type: str, data: bytes = PNG_1X1) -> UploadFile:
    file = UploadFile(
        filename=name,
        file=tempfile.SpooledTemporaryFile(max_size=1024 * 1024),
        headers={"content-type": content_type},
    )
    file.file.write(data)
    file.file.seek(0)
    return file


class UploadSecurityTests(unittest.TestCase):
    def test_image_rejects_non_image_content_type(self):
        file = make_upload_file("safe.png", "text/plain")
        try:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(_save_image(file, user_id=1))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("内容类型", ctx.exception.detail)
        finally:
            file.file.close()

    def test_image_markdown_alt_is_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = make_upload_file("bad](javascript:alert(1))\nname.png", "image/png")
            try:
                with patch("app.routers.images.get_user_images_dir", return_value=Path(tmp)):
                    result = asyncio.run(_save_image(file, user_id=1))
            finally:
                file.file.close()
        self.assertNotIn("](javascript", result["markdown"])
        self.assertNotIn("\n", result["markdown"])
        self.assertIn("\\]", result["markdown"])
        self.assertTrue(result["markdown"].startswith("!["))

    def test_material_extension_allowlist_is_narrow(self):
        self.assertEqual(ALLOWED_EXTENSIONS, {".pdf", ".docx", ".txt", ".md"})

    def test_material_content_type_mapping_rejects_common_mismatch(self):
        self.assertNotIn("text/html", ALLOWED_CONTENT_TYPES[".pdf"])
        self.assertNotIn("application/x-msdownload", ALLOWED_CONTENT_TYPES[".txt"])

    def test_material_default_upload_limit_is_200mb(self):
        self.assertEqual(MAX_FILE_SIZE, 200 * 1024 * 1024)

    def test_image_default_upload_limit_is_50mb(self):
        self.assertEqual(IMAGE_MAX_SIZE, 50 * 1024 * 1024)

    def test_image_read_limited_treats_zero_as_unlimited(self):
        file = make_upload_file("large.png", "image/png", PNG_1X1 + (b"x" * 1024))
        try:
            data = asyncio.run(_read_limited(file, max_size=0))
            self.assertGreater(len(data), 1024)
        finally:
            file.file.close()


if __name__ == "__main__":
    unittest.main()
