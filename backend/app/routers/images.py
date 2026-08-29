"""图片上传路由"""
from __future__ import annotations

import html
import os
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

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
    data = bytearray()
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if max_size > 0 and total > max_size:
            raise HTTPException(status_code=400, detail=detail)
        data.extend(chunk)
    return bytes(data)


def _validate_image_content(data: bytes) -> None:
    """Verify that image bytes can be parsed without accepting pixel bombs."""
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width < 1 or height < 1 or width * height > settings.MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=400, detail="图片像素尺寸超过限制")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="文件内容不是可用图片") from exc


def _validate_image_path(path: Path) -> None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width < 1 or height < 1 or width * height > settings.MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=400, detail="图片像素尺寸超过限制")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="文件内容不是可用图片") from exc


async def _save_image(file: UploadFile, user_id: int, max_size: int = MAX_SIZE) -> dict:
    ext = _validate_image_extension(file)
    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="上传内容类型必须是图片")
    ensure_data_dirs()
    dest_dir = get_user_images_dir(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    total = 0
    signature = bytearray()
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".upload-", suffix=".tmp", dir=dest_dir, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if max_size > 0 and total > max_size:
                    raise HTTPException(status_code=400, detail=f"图片大小不能超过 {settings.IMAGE_UPLOAD_MAX_MB} MB")
                if len(signature) < 16:
                    signature.extend(chunk[: 16 - len(signature)])
                temp_file.write(chunk)

        detected_ext = _detect_image_extension(bytes(signature))
        if detected_ext is None:
            raise HTTPException(status_code=400, detail="文件内容不是有效图片")
        if ext in {"jpg", "jpeg"}:
            ext = "jpg"
        if detected_ext != ext:
            raise HTTPException(status_code=400, detail="图片扩展名与实际文件内容不一致")
        _validate_image_path(temp_path)
        filename = f"{uuid.uuid4().hex}.{ext}"
        dest = dest_dir / filename
        os.replace(temp_path, dest)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

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


@router.post("/upload-background")
async def upload_background_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传自定义背景图，使用与普通图片相同的安全限制。"""
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
