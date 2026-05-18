"""Serve the built frontend from FastAPI for local packaged runs."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

_API_PREFIXES = ("api/",)
_RESERVED_PATHS = {"api", "docs", "redoc", "openapi.json", "health"}


def _is_reserved_path(path: str) -> bool:
    normalized = path.strip("/")
    return normalized in _RESERVED_PATHS or normalized.startswith(_API_PREFIXES)


def _safe_static_file(dist_dir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None

    candidate = (dist_dir / relative_path).resolve()
    try:
        candidate.relative_to(dist_dir.resolve())
    except ValueError:
        return None

    return candidate if candidate.is_file() else None


def register_frontend_static(app: FastAPI, dist_dir: Path) -> bool:
    """Register static frontend routes. Returns False when no build exists."""

    dist_dir = Path(dist_dir).resolve()
    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        logger.warning("Frontend build not found at %s; static UI disabled", index_file)
        return False

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        if _is_reserved_path(full_path):
            raise HTTPException(status_code=404, detail="Not Found")

        static_file = _safe_static_file(dist_dir, full_path)
        if static_file is not None:
            return FileResponse(static_file)

        return FileResponse(index_file)

    logger.info("Serving frontend build from %s", dist_dir)
    return True
