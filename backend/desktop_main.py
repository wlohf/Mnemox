"""Desktop-packaged backend entrypoint."""

from __future__ import annotations

import os

import uvicorn

from app.config import settings


def main() -> None:
    host = os.environ.get("HOST") or settings.HOST or "127.0.0.1"
    port = int(os.environ.get("PORT") or settings.PORT or 8000)
    uvicorn.run("app.main:app", host=host, port=port, reload=False, access_log=False)


if __name__ == "__main__":
    main()
