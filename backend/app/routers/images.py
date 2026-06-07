"""图片上传路由"""
from __future__ import annotations

import html
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import settings
from app.utils.paths import ensure_data_dirs, get_user_images_dir
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
MAX_SIZE = settings.IMAGE_UPLOAD_MAX_MB * 1024 * 1024


def _validate_image_extension(file: UploadFile) -> str:
    """Validate extension and return it (lowercase, without dot)."""
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式: .{ext}，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return ext


def _detect_image_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"BM"):
        return "bmp"
    return None


async def _read_limited(
    file: UploadFile,
    max_size: int,
    error_detail: str | None = None,
) -> bytes:
    detail = error_detail or f"图片大小不能超过 {settings.IMAGE_UPLOAD_MAX_MB} MB"
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise HTTPException(status_code=400, detail=detail)
        chunks.append(chunk)
    return b"".join(chunks)


async def _save_image(file: UploadFile, user_id: int) -> dict:
    ext = _validate_image_extension(file)
    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="上传内容类型必须是图片")
    data = await _read_limited(file, MAX_SIZE)
    detected_ext = _detect_image_extension(data)
    if detected_ext is None:
        raise HTTPException(status_code=400, detail="文件内容不是有效图片")
    if ext in {"jpg", "jpeg"}:
        ext = "jpg"
    if detected_ext != ext:
        raise HTTPException(status_code=400, detail="图片扩展名与实际文件内容不一致")

    ensure_data_dirs()
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest_dir = get_user_images_dir(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(data)

    url = f"/api/uploads/images/{user_id}/{filename}"
    original = file.filename or filename
    safe_alt = html.escape(original.replace("\r", " ").replace("\n", " "), quote=False)
    safe_alt = (
        safe_alt.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    return {
        "url": url,
        "filename": filename,
        "original_name": original,
        "markdown": f"![{safe_alt}]({url})",
    }


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传单张图片，返回 URL 和 Markdown 片段。"""
    return await _save_image(file, int(current_user.id))


@router.post("/upload-batch")
async def upload_images_batch(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    """批量上传图片。"""
    results = []
    user_id = int(current_user.id)
    for f in files:
        results.append(await _save_image(f, user_id))
    return results
