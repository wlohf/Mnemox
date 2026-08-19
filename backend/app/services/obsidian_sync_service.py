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

import hashlib
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
_SYNC_ACTIVE = "active"
_SYNC_MISSING = "missing"
_SYNC_CONFLICT = "conflict"
_CONFLICT_STRATEGIES = {"keep_local", "use_vault"}


class VaultPathError(ValueError):
    """vault 路径不合法或不被允许。"""


class VaultConflictError(ValueError):
    """vault 冲突不存在或解决策略无效。"""


class VaultFileError(ValueError):
    """单个 vault 文件不适合安全同步。"""


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


def _filesystem_identity(path: Path) -> str:
    """Return an identifier stable across same-volume renames and moves."""
    stat = path.stat()
    return f"{int(stat.st_dev)}:{int(stat.st_ino)}"


def _read_vault_markdown(vault: Path, file_path: Path) -> str:
    """Read one safe, complete UTF-8 Markdown file without silent truncation."""
    if file_path.is_symlink():
        raise VaultFileError("符号链接文件不允许同步")

    try:
        resolved = file_path.resolve(strict=True)
        resolved.relative_to(vault)
    except FileNotFoundError as exc:
        raise VaultFileError("文件在读取前已发生变化") from exc
    except ValueError as exc:
        raise VaultFileError("文件不在 Vault 授权目录内") from exc

    if not resolved.is_file():
        raise VaultFileError("不是可读取的普通文件")

    # UTF-8 code points are at most four bytes. Read one additional byte so a
    # growing or oversized file is rejected before it can be partially stored.
    max_bytes = MAX_NOTE_CHARS * 4
    with resolved.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise VaultFileError("文件内容超过单篇同步上限")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VaultFileError("文件不是 UTF-8 编码") from exc
    if len(content) > MAX_NOTE_CHARS:
        raise VaultFileError("文件内容超过单篇同步上限")
    return content


def _failure_summary(source_path: str, exc: Exception) -> dict[str, str]:
    reason = str(exc) if isinstance(exc, VaultFileError) else "文件读取失败"
    return {"source_path": source_path, "reason": reason}


def _snapshot_hash(title: str, content: str) -> str:
    payload = f"{title}\0{content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _note_snapshot_hash(note: Note) -> str:
    return _snapshot_hash(str(note.title or ""), str(note.content or ""))


def _clear_conflict(note: Note) -> None:
    note.source_conflict_title = None
    note.source_conflict_content = None
    note.source_conflict_hash = None
    note.source_conflict_vault_id = None
    note.source_conflict_file_id = None


def _conflict_summary(note: Note) -> dict[str, Any]:
    return {
        "note_id": int(note.id),
        "title": str(note.title or "未命名笔记"),
        "source_path": str(note.source_path or ""),
    }


async def _attach_notes_to_concepts(
    db: AsyncSession,
    user_id: int,
    notes: list[Note],
) -> None:
    for note in notes:
        try:
            from app.services.association_service import attach_note_to_concepts

            await attach_note_to_concepts(db, user_id, note)
        except Exception as exc:
            logger.warning("vault 笔记挂图失败 note_id=%s err=%s", note.id, exc)


async def sync_vault(
    db: AsyncSession,
    user_id: int,
    vault_path: str,
) -> dict[str, Any]:
    """Pull one vault snapshot without deleting or overwriting user changes."""
    vault = validate_vault_path(vault_path)
    vault_id = _filesystem_identity(vault)

    existing_result = await db.execute(
        select(Note).where(Note.user_id == user_id, Note.source_path.is_not(None))
    )
    existing_notes = list(existing_result.scalars().all())
    notes_by_identity: dict[str, Note] = {
        str(note.source_file_id): note
        for note in existing_notes
        if note.source_vault_id == vault_id and note.source_file_id
    }
    legacy_notes_by_path: dict[str, Note] = {
        str(note.source_path): note
        for note in existing_notes
        if note.source_path and not note.source_vault_id and not note.source_file_id
    }
    vault_notes_by_identity = dict(notes_by_identity)

    stats: dict[str, Any] = {
        "scanned": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "truncated": False,
        "renamed": 0,
        "missing": 0,
        "conflicted": 0,
        "conflicts": [],
        "failures": [],
    }
    changed_notes: list[Note] = []
    seen_file_ids: set[str] = set()

    for file_path, source_path in _iter_markdown_files(vault):
        if stats["scanned"] >= MAX_FILES_PER_SYNC:
            stats["truncated"] = True
            break
        stats["scanned"] += 1
        try:
            content = _read_vault_markdown(vault, file_path)
            title = file_path.stem[:200] or "未命名笔记"
            file_id = _filesystem_identity(file_path)
            seen_file_ids.add(file_id)
            incoming_hash = _snapshot_hash(title, content)
            note = notes_by_identity.get(file_id)
            matched_legacy_path = note is None and source_path in legacy_notes_by_path
            if note is None:
                note = legacy_notes_by_path.get(source_path)
            if note is None:
                note = Note(
                    user_id=user_id,
                    title=title,
                    content=content,
                    note_type="general",
                    tags="[]",
                    source_path=source_path,
                    source_vault_id=vault_id,
                    source_file_id=file_id,
                    source_sync_hash=incoming_hash,
                    source_sync_state=_SYNC_ACTIVE,
                )
                db.add(note)
                await db.flush()
                notes_by_identity[file_id] = note
                vault_notes_by_identity[file_id] = note
                stats["created"] += 1
                changed_notes.append(note)
            else:
                previous_path = str(note.source_path or "")
                if previous_path != source_path:
                    note.source_path = source_path
                    stats["renamed"] += 1

                if matched_legacy_path:
                    # A relative path alone is not enough evidence to overwrite a
                    # legacy local note: it may be a different vault, or have
                    # diverged before stable file identity was introduced.
                    if _note_snapshot_hash(note) != incoming_hash:
                        note.source_sync_state = _SYNC_CONFLICT
                        note.source_conflict_title = title
                        note.source_conflict_content = content
                        note.source_conflict_hash = incoming_hash
                        note.source_conflict_vault_id = vault_id
                        note.source_conflict_file_id = file_id
                        stats["conflicted"] += 1
                        stats["conflicts"].append(_conflict_summary(note))
                        continue

                    note.source_vault_id = vault_id
                    note.source_file_id = file_id
                    notes_by_identity[file_id] = note
                    vault_notes_by_identity[file_id] = note
                    note.source_sync_hash = incoming_hash
                    note.source_sync_state = _SYNC_ACTIVE
                    _clear_conflict(note)
                    stats["skipped"] += 1
                    continue

                note.source_vault_id = vault_id
                note.source_file_id = file_id
                notes_by_identity[file_id] = note
                vault_notes_by_identity[file_id] = note

                baseline_hash = str(note.source_sync_hash or _note_snapshot_hash(note))
                remote_changed = incoming_hash != baseline_hash
                local_changed = _note_snapshot_hash(note) != baseline_hash
                if remote_changed and local_changed:
                    note.source_sync_state = _SYNC_CONFLICT
                    note.source_conflict_title = title
                    note.source_conflict_content = content
                    note.source_conflict_hash = incoming_hash
                    stats["conflicted"] += 1
                    stats["conflicts"].append(_conflict_summary(note))
                elif remote_changed:
                    note.title = title
                    note.content = content
                    note.source_sync_hash = incoming_hash
                    note.source_sync_state = _SYNC_ACTIVE
                    _clear_conflict(note)
                    stats["updated"] += 1
                    changed_notes.append(note)
                else:
                    note.source_sync_state = _SYNC_ACTIVE
                    _clear_conflict(note)
                    stats["skipped"] += 1
        except Exception as exc:
            stats["failed"] += 1
            stats["failures"].append(_failure_summary(source_path, exc))
            logger.warning("vault 文件同步失败 path=%s err=%s", source_path, exc)

    # A partial or failed scan cannot distinguish an unseen file from a deleted
    # file, so retain the last known state until a complete scan succeeds.
    if not stats["truncated"] and stats["failed"] == 0:
        for file_id, note in vault_notes_by_identity.items():
            if file_id not in seen_file_ids and note.source_sync_state not in {_SYNC_MISSING, _SYNC_CONFLICT}:
                note.source_sync_state = _SYNC_MISSING
                stats["missing"] += 1

    await _attach_notes_to_concepts(db, user_id, changed_notes)

    await db.flush()
    return stats


async def resolve_vault_conflict(
    db: AsyncSession,
    user_id: int,
    note_id: int,
    strategy: str,
) -> dict[str, Any]:
    """Resolve a stored pull-sync conflict without performing a vault write."""
    selected = str(strategy or "").strip()
    if selected not in _CONFLICT_STRATEGIES:
        raise VaultConflictError("不支持的冲突解决策略")

    result = await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.user_id == user_id,
            Note.source_sync_state == _SYNC_CONFLICT,
        )
    )
    note = result.scalar_one_or_none()
    if note is None or not note.source_conflict_hash:
        raise VaultConflictError("未找到待解决的 vault 冲突")

    if selected == "use_vault":
        note.title = note.source_conflict_title or note.title
        note.content = note.source_conflict_content or ""
        await _attach_notes_to_concepts(db, user_id, [note])

    if (
        not note.source_vault_id
        and note.source_conflict_vault_id
        and note.source_conflict_file_id
    ):
        note.source_vault_id = note.source_conflict_vault_id
        note.source_file_id = note.source_conflict_file_id

    # Keep the accepted vault revision as the new comparison baseline. A later
    # vault edit will surface as a new conflict if the local note still differs.
    note.source_sync_hash = note.source_conflict_hash
    note.source_sync_state = _SYNC_ACTIVE
    _clear_conflict(note)
    await db.flush()
    return {
        "ok": True,
        "note_id": int(note.id),
        "strategy": selected,
        "title": str(note.title or "未命名笔记"),
        "source_path": str(note.source_path or ""),
    }
