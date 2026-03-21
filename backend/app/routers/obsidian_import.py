"""Obsidian 笔记导入路由。

处理 Obsidian 格式的 Markdown 文件和附件图片：
- 将附件图片保存到 data/uploads/images/
- 把 ![[image.png]] / ![[image.png|400]] / ![alt](relative/path.png) 替换为绝对 URL
"""
from __future__ import annotations

import re
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.paths import get_images_dir
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
router = APIRouter()

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"}


def _ext_ok(name: str) -> bool:
    return name.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS if "." in name else False


async def _save_attachment(file: UploadFile) -> tuple[str, str]:
    """Save an attachment image and return (original_name, url)."""
    original = file.filename or "unknown.png"
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else "png"
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = get_images_dir() / filename
    dest.write_bytes(await file.read())
    return original, f"/api/uploads/images/{filename}"


def _replace_image_refs(md: str, name_to_url: dict[str, str]) -> tuple[str, list[str]]:
    """Replace Obsidian image references with standard markdown URLs.

    Returns (new_content, warnings).
    """
    warnings: list[str] = []

    def _lookup(name: str) -> str | None:
        # exact match first
        if name in name_to_url:
            return name_to_url[name]
        # try basename (for "attachments/image.png")
        base = PurePosixPath(name).name
        if base in name_to_url:
            return name_to_url[base]
        return None

    # 1) Obsidian wikilink: ![[name]] or ![[name|width]]
    def _wiki_repl(m: re.Match) -> str:
        raw = m.group(1)
        name = raw.split("|")[0].strip()
        url = _lookup(name)
        if url is None:
            warnings.append(f"未找到附件: {name}")
            return m.group(0)
        return f"![{PurePosixPath(name).stem}]({url})"

    md = re.sub(r"!\[\[(.+?)]]", _wiki_repl, md)

    # 2) Standard markdown image with relative path: ![alt](path)
    def _md_repl(m: re.Match) -> str:
        alt = m.group(1)
        path = m.group(2)
        # skip absolute URLs
        if path.startswith(("http://", "https://", "/api/")):
            return m.group(0)
        url = _lookup(path)
        if url is None:
            # try basename
            base = PurePosixPath(path).name
            url = _lookup(base)
        if url is None:
            warnings.append(f"未找到附件: {path}")
            return m.group(0)
        return f"![{alt}]({url})"

    md = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _md_repl, md)

    return md, warnings


@router.post("/import")
async def import_obsidian_note(
    md_file: UploadFile = File(...),
    attachments: list[UploadFile] = File(default=[]),
    title: str | None = Form(default=None),
    save_to_db: bool = Form(default=True, description="是否自动保存到笔记数据库"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入 Obsidian 笔记（.md 文件 + 附件图片）。"""
    # Read markdown content
    raw = await md_file.read()
    try:
        md_content = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            md_content = raw.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="无法解码 Markdown 文件，请使用 UTF-8 编码")

    # Determine title
    note_title = title
    if not note_title:
        fname = md_file.filename or "导入笔记"
        note_title = fname.rsplit(".", 1)[0] if "." in fname else fname

    # Save attachments and build mapping
    name_to_url: dict[str, str] = {}
    images_uploaded = 0
    for att in attachments:
        att_name = att.filename or ""
        if not _ext_ok(att_name):
            continue
        original, url = await _save_attachment(att)
        name_to_url[original] = url
        # also map basename in case of path prefix
        base = PurePosixPath(original).name
        if base != original:
            name_to_url[base] = url
        images_uploaded += 1

    # Replace references
    final_content, warnings = _replace_image_refs(md_content, name_to_url)

    # 自动保存到笔记数据库，避免图片已上传但笔记丢失
    note_id = None
    if save_to_db:
        from app.models.note import Note
        import json as _json
        note = Note(
            user_id=current_user.id,
            title=note_title,
            content=final_content,
            note_type="general",
            tags=_json.dumps(["obsidian-import"]),
        )
        db.add(note)
        await db.flush()
        await db.refresh(note)
        note_id = note.id

    return {
        "title": note_title,
        "content": final_content,
        "images_uploaded": images_uploaded,
        "warnings": warnings,
        "note_id": note_id,
        "saved_to_db": save_to_db,
    }
