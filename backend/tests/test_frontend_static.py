import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend_static import register_frontend_static
from app.main import _resolve_frontend_dist_dir


class FrontendStaticTests(unittest.TestCase):
    def test_register_frontend_static_serves_spa_without_hiding_api_404s(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "assets").mkdir()
            (dist / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
            (dist / "manifest.json").write_text("{\"name\":\"Mnemox\"}", encoding="utf-8")
            (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

            app = FastAPI()

            @app.get("/api/ping")
            async def ping():
                return {"ok": True}

            self.assertTrue(register_frontend_static(app, dist))
            client = TestClient(app)

            self.assertEqual(client.get("/api/ping").json(), {"ok": True})
            self.assertEqual(client.get("/api/missing").status_code, 404)
            self.assertIn("root", client.get("/").text)
            self.assertIn("root", client.get("/notes/123").text)
            self.assertEqual(client.get("/manifest.json").json(), {"name": "Mnemox"})
            self.assertEqual(client.get("/assets/app.js").text, "console.log('ok')")

    def test_register_frontend_static_is_disabled_when_index_is_missing(self):
        app = FastAPI()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(register_frontend_static(app, Path(tmp)))

    def test_resolve_frontend_dist_dir_accepts_absolute_packaged_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "frontend" / "dist"
            with patch("app.main.settings.FRONTEND_DIST_DIR", str(dist)):
                self.assertEqual(_resolve_frontend_dist_dir(), dist.resolve())

    def test_resolve_frontend_dist_dir_keeps_relative_path_repo_scoped(self):
        with patch("app.main.settings.FRONTEND_DIST_DIR", "frontend/dist"):
            self.assertEqual(
                _resolve_frontend_dist_dir(),
                (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
