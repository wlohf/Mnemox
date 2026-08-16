"""Obsidian vault 增量同步测试（决策 D6）。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.concept import ConceptLink
from app.models.note import Note
from app.models.user import User
from app.services.concept_service import upsert_concept
from app.services import obsidian_sync_service
from app.services.obsidian_sync_service import (
    VaultPathError,
    resolve_vault_conflict,
    sync_vault,
    validate_vault_path,
)


class VaultSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        db_path = base / "vault_sync.sqlite3"
        self.vault = base / "vault"
        (self.vault / "folder").mkdir(parents=True)
        (self.vault / ".obsidian").mkdir()

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    def _write(self, relative: str, content: str) -> None:
        target = self.vault / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def test_first_sync_creates_notes_and_config_dirs_are_skipped(self):
        # Arrange
        user_id = await self._create_user("vault_user")
        self._write("每日复盘.md", "今天复盘了条件概率")
        self._write("folder/读书笔记.md", "# 心得\n坚持比方法重要")
        self._write(".obsidian/config.md", "不应被导入")

        # Act
        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        # Assert
        self.assertEqual(stats["created"], 2)
        self.assertEqual(stats["failed"], 0)
        async with self.sessionmaker() as session:
            notes = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalars().all()
        titles = {n.title for n in notes}
        self.assertEqual(titles, {"每日复盘", "读书笔记"})
        paths = {n.source_path for n in notes}
        self.assertIn("folder/读书笔记.md", paths)

    async def test_second_sync_skips_unchanged_and_updates_changed(self):
        # Arrange
        user_id = await self._create_user("vault_incr_user")
        self._write("a.md", "版本一")
        self._write("b.md", "保持不变")
        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self._write("a.md", "版本二：新增了贝叶斯内容")

        # Act
        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        # Assert
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["skipped"], 1)
        async with self.sessionmaker() as session:
            note = (
                await session.execute(
                    select(Note).where(Note.user_id == user_id, Note.source_path == "a.md")
                )
            ).scalar_one()
        self.assertIn("版本二", note.content)

    async def test_legacy_source_path_with_different_local_content_requires_conflict_resolution(self):
        user_id = await self._create_user("vault_legacy_conflict_user")
        self._write("legacy/同名笔记.md", "Vault 版本")
        async with self.sessionmaker() as session:
            note = Note(
                user_id=user_id,
                title="同名笔记",
                content="Mnemox 本地版本",
                note_type="general",
                tags="[]",
                source_path="legacy/同名笔记.md",
            )
            session.add(note)
            await session.commit()

        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["conflicted"], 1)
        async with self.sessionmaker() as session:
            notes = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalars().all()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].content, "Mnemox 本地版本")
        self.assertEqual(notes[0].source_sync_state, "conflict")
        self.assertEqual(notes[0].source_conflict_content, "Vault 版本")

    async def test_renamed_file_keeps_the_existing_note_identity(self):
        user_id = await self._create_user("vault_rename_user")
        self._write("旧目录/学习记录.md", "重命名后仍应是同一篇笔记。")

        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()
            original = (
                await session.execute(
                    select(Note).where(Note.user_id == user_id, Note.source_path == "旧目录/学习记录.md")
                )
            ).scalar_one()
            original_id = original.id

        source = self.vault / "旧目录/学习记录.md"
        target = self.vault / "归档/复习记录.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)

        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["renamed"], 1)
        async with self.sessionmaker() as session:
            notes = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalars().all()
        self.assertEqual([(note.id, note.source_path) for note in notes], [(original_id, "归档/复习记录.md")])

    async def test_missing_vault_file_is_marked_without_deleting_the_note(self):
        user_id = await self._create_user("vault_missing_user")
        self._write("待删除.md", "保留 Mnemox 笔记，等待用户处理。")

        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        (self.vault / "待删除.md").unlink()
        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self.assertEqual(stats["missing"], 1)
        async with self.sessionmaker() as session:
            note = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalar_one()
        self.assertEqual(note.source_sync_state, "missing")
        self.assertEqual(note.content, "保留 Mnemox 笔记，等待用户处理。")

    async def test_truncated_sync_never_marks_unscanned_vault_notes_missing(self):
        user_id = await self._create_user("vault_truncated_user")
        self._write("a.md", "A")
        self._write("b.md", "B")
        async with self.sessionmaker() as session:
            with patch.object(obsidian_sync_service, "MAX_FILES_PER_SYNC", 2):
                await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        async with self.sessionmaker() as session:
            with patch.object(obsidian_sync_service, "MAX_FILES_PER_SYNC", 1):
                stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self.assertTrue(stats["truncated"])
        self.assertEqual(stats["missing"], 0)
        async with self.sessionmaker() as session:
            notes = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalars().all()
        self.assertEqual({note.source_sync_state for note in notes}, {"active"})

    async def test_conflicting_vault_change_preserves_local_note_and_records_external_candidate(self):
        user_id = await self._create_user("vault_conflict_user")
        self._write("冲突笔记.md", "vault 版本一")

        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()
            note = (
                await session.execute(
                    select(Note).where(Note.user_id == user_id, Note.source_path == "冲突笔记.md")
                )
            ).scalar_one()
            note.content = "Mnemox 本地修改"
            await session.commit()

        self._write("冲突笔记.md", "vault 版本二")
        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self.assertEqual(stats["conflicted"], 1)
        self.assertEqual(len(stats["conflicts"]), 1)
        async with self.sessionmaker() as session:
            note = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalar_one()
        self.assertEqual(note.content, "Mnemox 本地修改")
        self.assertEqual(note.source_sync_state, "conflict")
        self.assertEqual(note.source_conflict_content, "vault 版本二")

    async def test_conflict_resolution_keep_local_preserves_note_and_accepts_vault_baseline(self):
        user_id = await self._create_user("vault_keep_local_user")
        self._write("冲突保留本地.md", "vault 版本一")

        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()
            note = (
                await session.execute(
                    select(Note).where(Note.user_id == user_id, Note.source_path == "冲突保留本地.md")
                )
            ).scalar_one()
            note_id = int(note.id)
            note.content = "Mnemox 保留版本"
            await session.commit()

        self._write("冲突保留本地.md", "vault 版本二")
        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            result = await resolve_vault_conflict(session, user_id, note_id, "keep_local")
            await session.commit()

        self.assertEqual(result["strategy"], "keep_local")
        async with self.sessionmaker() as session:
            note = (
                await session.execute(select(Note).where(Note.id == note_id))
            ).scalar_one()
        self.assertEqual(note.content, "Mnemox 保留版本")
        self.assertEqual(note.source_sync_state, "active")
        self.assertIsNone(note.source_conflict_content)

    async def test_conflict_resolution_use_vault_replaces_local_note_with_candidate(self):
        user_id = await self._create_user("vault_use_vault_user")
        self._write("冲突采用Vault.md", "vault 版本一")

        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()
            note = (
                await session.execute(
                    select(Note).where(Note.user_id == user_id, Note.source_path == "冲突采用Vault.md")
                )
            ).scalar_one()
            note_id = int(note.id)
            note.content = "Mnemox 将被替换版本"
            await session.commit()

        self._write("冲突采用Vault.md", "vault 版本二")
        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            result = await resolve_vault_conflict(session, user_id, note_id, "use_vault")
            await session.commit()

        self.assertEqual(result["strategy"], "use_vault")
        async with self.sessionmaker() as session:
            note = (
                await session.execute(select(Note).where(Note.id == note_id))
            ).scalar_one()
        self.assertEqual(note.content, "vault 版本二")
        self.assertEqual(note.source_sync_state, "active")
        self.assertIsNone(note.source_conflict_content)

    async def test_vault_revert_to_baseline_clears_stale_conflict_candidate(self):
        user_id = await self._create_user("vault_revert_conflict_user")
        self._write("回滚冲突.md", "vault 基线")

        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()
            note = (
                await session.execute(
                    select(Note).where(Note.user_id == user_id, Note.source_path == "回滚冲突.md")
                )
            ).scalar_one()
            note.content = "Mnemox 本地修改"
            await session.commit()

        self._write("回滚冲突.md", "vault 候选版本")
        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self._write("回滚冲突.md", "vault 基线")
        async with self.sessionmaker() as session:
            stats = await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        self.assertEqual(stats["conflicted"], 0)
        async with self.sessionmaker() as session:
            note = (
                await session.execute(select(Note).where(Note.user_id == user_id))
            ).scalar_one()
        self.assertEqual(note.source_sync_state, "active")
        self.assertIsNone(note.source_conflict_content)

    async def test_synced_note_attaches_to_existing_concepts(self):
        # Arrange：先有概念"条件概率"，vault 文件提到它
        user_id = await self._create_user("vault_concept_user")
        async with self.sessionmaker() as session:
            concept = await upsert_concept(session, user_id, "条件概率")
            await session.commit()
            concept_id = concept.id
        self._write("学习记录.md", "今天搞懂了条件概率的定义")

        # Act
        async with self.sessionmaker() as session:
            await sync_vault(session, user_id, str(self.vault))
            await session.commit()

        # Assert
        async with self.sessionmaker() as session:
            link = (
                await session.execute(
                    select(ConceptLink).where(
                        ConceptLink.user_id == user_id,
                        ConceptLink.concept_id == concept_id,
                        ConceptLink.target_type == "note",
                    )
                )
            ).scalar_one_or_none()
        self.assertIsNotNone(link)

    async def test_invalid_vault_path_raises(self):
        with self.assertRaises(VaultPathError):
            validate_vault_path("")
        with self.assertRaises(VaultPathError):
            validate_vault_path(str(Path(self.tmpdir.name) / "not-exists"))

    async def test_production_requires_configured_root(self):
        from app.services import obsidian_sync_service

        original = obsidian_sync_service.settings.ENVIRONMENT
        obsidian_sync_service.settings.ENVIRONMENT = "production"
        try:
            with self.assertRaises(VaultPathError):
                validate_vault_path(str(self.vault))
        finally:
            obsidian_sync_service.settings.ENVIRONMENT = original


if __name__ == "__main__":
    unittest.main()
