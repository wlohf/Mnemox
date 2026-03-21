"""图片上传路由"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.utils.paths import get_images_dir
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def _validate_image(file: UploadFile) -> str:
    """Validate extension and return it (lowercase, without dot)."""
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式: .{ext}，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return ext


async def _save_image(file: UploadFile) -> dict:
    ext = _validate_image(file)
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10 MB")

    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = get_images_dir() / filename
    dest.write_bytes(data)

    url = f"/api/uploads/images/{filename}"
    original = file.filename or filename
    return {
        "url": url,
        "filename": filename,
        "original_name": original,
        "markdown": f"![{original}]({url})",
    }


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传单张图片，返回 URL 和 Markdown 片段。"""
    return await _save_image(file)


@router.post("/upload-batch")
async def upload_images_batch(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    """批量上传图片。"""
    results = []
    for f in files:
        results.append(await _save_image(f))
    return results
