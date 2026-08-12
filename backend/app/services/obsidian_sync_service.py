"""Obsidian vault 增量同步（决策 D6）：监听式导入的拉取实现。

以 vault 内相对路径为幂等键（notes.source_path）做增量 upsert：
- 新文件 → 创建笔记；内容变化 → 更新；未变化 → 跳过。
- 同步后的新/变更笔记自动挂概念图（联想引擎入口之一）。
- 单文件失败只计数不中断；本函数即后续 watchdog 实时监听要调用的同步核心。

安全边界：vault 路径由 `validate_vault_path` 校验——生产环境必须配置
`OBSIDIAN_VAULT_ROOT` 白名单根目录；开发/桌面本地环境允许任意本地目录
（后端运行在用户自己的机器上，与现有本地上传同一信任模型）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.note import Note

logger = logging.getLogger(__name__)

MAX_FILES_PER_SYNC = 500
MAX_NOTE_CHARS = 200_000
_SKIP_DIR_PREFIXES = (".",)  # .obsidian / .trash / .git 等


class VaultPathError(ValueError):
    """vault 路径不合法或不被允许。"""


def validate_vault_path(vault_path: str) -> Path:
    """校验并解析 vault 路径（生产环境强制白名单根目录）。"""
    raw = str(vault_path or "").strip()
    if not raw:
        raise VaultPathError("vault 路径不能为空")
    path = Path(raw).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        raise VaultPathError(f"vault 路径无法解析：{exc}") from exc

    root_setting = (settings.OBSIDIAN_VAULT_ROOT or "").strip()
    if root_setting:
        root = Path(root_setting).expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise VaultPathError("vault 路径不在允许的根目录内") from exc
    elif settings.ENVIRONMENT.lower() in {"prod", "production"}:
        raise VaultPathError("生产环境需先配置 OBSIDIAN_VAULT_ROOT 才能使用 vault 同步")

    if not path.is_dir():
        raise VaultPathError("vault 路径不存在或不是目录")
    return path


def _iter_markdown_files(vault: Path):
    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault)
        if any(part.startswith(_SKIP_DIR_PREFIXES) for part in relative.parts[:-1]):
            continue
        yield path, relative.as_posix()


async def sync_vault(
    db: AsyncSession,
    user_id: int,
    vault_path: str,
) -> dict[str, Any]:
    """对 vault 做一次增量同步，返回统计。"""
    vault = validate_vault_path(vault_path)

    existing_result = await db.execute(
        select(Note).where(Note.user_id == user_id, Note.source_path.is_not(None))
    )
    notes_by_path: dict[str, Note] = {
        str(note.source_path): note for note in existing_result.scalars().all()
    }

    stats = {"scanned": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0, "truncated": False}
    changed_notes: list[Note] = []

    for file_path, source_path in _iter_markdown_files(vault):
        if stats["scanned"] >= MAX_FILES_PER_SYNC:
            stats["truncated"] = True
            break
        stats["scanned"] += 1
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")[:MAX_NOTE_CHARS]
            title = file_path.stem[:200] or "未命名笔记"
            note = notes_by_path.get(source_path)
            if note is None:
                note = Note(
                    user_id=user_id,
                    title=title,
                    content=content,
                    note_type="general",
                    tags="[]",
                    source_path=source_path,
                )
                db.add(note)
                await db.flush()
                notes_by_path[source_path] = note
                stats["created"] += 1
                changed_notes.append(note)
            elif (note.content or "") != content or (note.title or "") != title:
                note.title = title
                note.content = content
                stats["updated"] += 1
                changed_notes.append(note)
            else:
                stats["skipped"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("vault 文件同步失败 path=%s err=%s", source_path, exc)

    # 新/变更笔记挂概念图（失败不影响同步结果）
    for note in changed_notes:
        try:
            from app.services.association_service import attach_note_to_concepts

            await attach_note_to_concepts(db, user_id, note)
        except Exception as exc:
            logger.warning("vault 笔记挂图失败 note_id=%s err=%s", note.id, exc)

    await db.flush()
    return stats
