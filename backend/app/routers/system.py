"""系统相关路由：版本与更新检查"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import settings
from app.models.user import User

router = APIRouter()


class VersionInfoOut(BaseModel):
    app_name: str
    current_version: str
    checked_at: str


class UpdateInfoOut(BaseModel):
    has_update: bool
    current_version: str
    latest_version: Optional[str] = None
    release_notes: Optional[str] = None
    release_page: Optional[str] = None
    download_url: Optional[str] = None
    published_at: Optional[str] = None
    checked_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_version(version: str) -> list[int]:
    if not version:
        return [0, 0, 0]
    v = version.strip().lower()
    if v.startswith("v"):
        v = v[1:]
    parts = []
    for seg in v.split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[:3]


def _is_newer(latest: str, current: str) -> bool:
    return _normalize_version(latest) > _normalize_version(current)


def _pick_download_url(platform_links: object) -> Optional[str]:
    if isinstance(platform_links, dict):
        for key in ("windows", "win", "mac", "darwin", "linux", "universal"):
            value = platform_links.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(platform_links, str) and platform_links.strip():
        return platform_links.strip()
    return None


def _parse_manifest(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="更新源响应格式错误，应为 JSON 对象")
    return payload


@router.get("/version", response_model=VersionInfoOut)
async def get_version(_current_user: User = Depends(get_current_user)):
    """返回当前应用版本"""
    return VersionInfoOut(
        app_name="Study Assistant",
        current_version=settings.APP_VERSION,
        checked_at=_now_iso(),
    )


@router.get("/update-check", response_model=UpdateInfoOut)
async def check_update(_current_user: User = Depends(get_current_user)):
    """
    检查是否有新版本。
    需要配置 APP_UPDATE_MANIFEST_URL 指向 JSON 清单，例如：
    {
      "latest_version": "1.0.1",
      "release_notes": "修复若干问题",
      "release_page": "https://example.com/releases/1.0.1",
      "published_at": "2026-04-24T10:00:00Z",
      "downloads": {"windows": "https://example.com/app-1.0.1.exe"}
    }
    """
    checked_at = _now_iso()
    manifest_url = (settings.APP_UPDATE_MANIFEST_URL or "").strip()
    if not manifest_url:
        return UpdateInfoOut(
            has_update=False,
            current_version=settings.APP_VERSION,
            latest_version=settings.APP_VERSION,
            checked_at=checked_at,
            release_notes="未配置更新源（APP_UPDATE_MANIFEST_URL）",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(manifest_url)
            response.raise_for_status()
            payload = _parse_manifest(response.json())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"更新源访问失败: {exc}")
    except ValueError:
        raise HTTPException(status_code=502, detail="更新源响应不是合法 JSON")

    latest_version = str(payload.get("latest_version") or "").strip()
    if not latest_version:
        raise HTTPException(status_code=502, detail="更新源缺少 latest_version 字段")

    release_notes = payload.get("release_notes")
    release_page = payload.get("release_page")
    published_at = payload.get("published_at")
    download_url = _pick_download_url(payload.get("downloads")) or _pick_download_url(
        payload.get("download_url")
    )
    has_update = _is_newer(latest_version, settings.APP_VERSION)

    return UpdateInfoOut(
        has_update=has_update,
        current_version=settings.APP_VERSION,
        latest_version=latest_version,
        release_notes=str(release_notes) if isinstance(release_notes, str) else None,
        release_page=str(release_page) if isinstance(release_page, str) else None,
        download_url=download_url,
        published_at=str(published_at) if isinstance(published_at, str) else None,
        checked_at=checked_at,
    )
