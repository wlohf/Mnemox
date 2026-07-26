"""自引激励（引用用户自己的笔记）测试：选取、冷却、反馈回写、技能渲染。"""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.note import Note
from app.models.note_quote import NoteQuoteUsage
from app.models.user import User
from app.services.coach_skills.base import CoachSkillContext
from app.services.coach_skills.low_motivation import LowMotivationSkill
from app.services.motivation_service import _collect_recent_note_highlights
from app.services.note_quote_service import (
    attach_note_quote_feedback,
    record_note_quote_usage,
    recently_used_hashes,
    select_note_quote,
)

PERSISTENCE_NOTE = "坚持从来不是在你想做的时候去做，而是在你不想做的时候仍然去做。"
METHOD_NOTE = "先理解再记忆，方法比时长重要，复盘要落在具体行动上。"


class NoteQuoteServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "note_quote.sqlite3"
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

    async def _create_note(self, user_id: int, title: str, content: str, note_type: str = "general") -> None:
        async with self.sessionmaker() as session:
            session.add(Note(user_id=user_id, title=title, content=content, note_type=note_type))
            await session.commit()

    async def test_select_note_quote_returns_excerpt_with_provenance(self):
        # Arrange
        user_id = await self._create_user("quote_user")
        await self._create_note(user_id, "读书笔记", PERSISTENCE_NOTE)

        # Act
        async with self.sessionmaker() as session:
            quote = await select_note_quote(session, user_id)

        # Assert
        self.assertIsNotNone(quote)
        self.assertIn("坚持从来不是", quote["excerpt"])
        self.assertEqual(quote["title"], "读书笔记")
        self.assertTrue(quote["reference_title"])
        self.assertTrue(quote["excerpt_hash"])
        self.assertIsNotNone(quote["note_id"])

    async def test_select_note_quote_prefers_review_type_notes(self):
        # Arrange: general 笔记更新更晚，但 review（心得）类应优先
        user_id = await self._create_user("prefer_user")
        await self._create_note(user_id, "复盘心得", METHOD_NOTE, note_type="review")
        await self._create_note(user_id, "普通摘录", PERSISTENCE_NOTE, note_type="general")

        # Act
        async with self.sessionmaker() as session:
            quote = await select_note_quote(session, user_id)

        # Assert
        self.assertEqual(quote["title"], "复盘心得")

    async def test_quoted_excerpt_is_not_repeated_within_cooldown(self):
        # Arrange
        user_id = await self._create_user("cooldown_user")
        await self._create_note(user_id, "读书笔记", PERSISTENCE_NOTE)
        await self._create_note(user_id, "方法笔记", METHOD_NOTE)

        async with self.sessionmaker() as session:
            first = await select_note_quote(session, user_id)
            await record_note_quote_usage(session, user_id, first, channel="coach", nudge_id="nudge_1")
            await session.commit()

        # Act
        async with self.sessionmaker() as session:
            second = await select_note_quote(session, user_id)

        # Assert: 冷却期内换下一条；两条都用过之后返回 None
        self.assertIsNotNone(second)
        self.assertNotEqual(second["excerpt_hash"], first["excerpt_hash"])

        async with self.sessionmaker() as session:
            await record_note_quote_usage(session, user_id, second, channel="coach", nudge_id="nudge_2")
            await session.commit()
        async with self.sessionmaker() as session:
            third = await select_note_quote(session, user_id)
        self.assertIsNone(third)

    async def test_cooldown_expires_after_window(self):
        # Arrange
        user_id = await self._create_user("expire_user")
        await self._create_note(user_id, "读书笔记", PERSISTENCE_NOTE)
        old_time = datetime.now() - timedelta(days=30)

        async with self.sessionmaker() as session:
            quote = await select_note_quote(session, user_id)
            await record_note_quote_usage(session, user_id, quote, channel="coach", now=old_time)
            await session.commit()

        # Act
        async with self.sessionmaker() as session:
            hashes = await recently_used_hashes(session, user_id)
            again = await select_note_quote(session, user_id)

        # Assert: 30 天前的引用已出冷却期，可再次引用
        self.assertEqual(hashes, set())
        self.assertIsNotNone(again)

    async def test_attach_feedback_updates_usage_rows(self):
        # Arrange
        user_id = await self._create_user("feedback_user")
        await self._create_note(user_id, "读书笔记", PERSISTENCE_NOTE)
        async with self.sessionmaker() as session:
            quote = await select_note_quote(session, user_id)
            await record_note_quote_usage(session, user_id, quote, channel="coach", nudge_id="nudge_x")
            await session.commit()

        # Act
        async with self.sessionmaker() as session:
            updated = await attach_note_quote_feedback(session, user_id, "nudge_x", "helpful")
            await session.commit()

        # Assert
        self.assertEqual(updated, 1)
        async with self.sessionmaker() as session:
            row = (
                await session.execute(select(NoteQuoteUsage).where(NoteQuoteUsage.nudge_id == "nudge_x"))
            ).scalar_one()
            self.assertEqual(row.feedback_outcome, "helpful")

    async def test_usage_is_isolated_per_user(self):
        # Arrange: 用户 B 的引用记录不应影响用户 A 的冷却
        user_a = await self._create_user("iso_a")
        user_b = await self._create_user("iso_b")
        await self._create_note(user_a, "读书笔记", PERSISTENCE_NOTE)
        await self._create_note(user_b, "读书笔记", PERSISTENCE_NOTE)

        async with self.sessionmaker() as session:
            quote_b = await select_note_quote(session, user_b)
            await record_note_quote_usage(session, user_b, quote_b, channel="coach")
            await session.commit()

        # Act
        async with self.sessionmaker() as session:
            quote_a = await select_note_quote(session, user_a)

        # Assert
        self.assertIsNotNone(quote_a)

    async def test_motivation_highlights_exclude_cooldown_hashes(self):
        # Arrange
        user_id = await self._create_user("highlight_user")
        await self._create_note(user_id, "读书笔记", PERSISTENCE_NOTE)
        await self._create_note(user_id, "方法笔记", METHOD_NOTE)

        async with self.sessionmaker() as session:
            all_highlights = await _collect_recent_note_highlights(session, user_id)
            excluded = {all_highlights[0].excerpt_hash}

            # Act
            filtered = await _collect_recent_note_highlights(session, user_id, exclude_hashes=excluded)

        # Assert
        self.assertEqual(len(all_highlights), 2)
        self.assertEqual(len(filtered), 1)
        self.assertNotIn(filtered[0].excerpt_hash, excluded)


class NoteQuoteSkillRenderingTests(unittest.IsolatedAsyncioTestCase):
    def _make_ctx(self, note_quote=None):
        snapshot = {"tasks": {}, "review": {"due_review_count": 1}}
        if note_quote is not None:
            snapshot["note_quote"] = note_quote
        return CoachSkillContext(
            user_id=1,
            event={"event_type": "chat.low_motivation_detected", "payload": {}},
            snapshot=snapshot,
            policy={},
        )

    async def test_low_motivation_skill_appends_verbatim_quote_with_source(self):
        # Arrange
        quote = {
            "note_id": 7,
            "title": "读书笔记",
            "excerpt": PERSISTENCE_NOTE.rstrip("。"),
            "excerpt_hash": "abc123",
            "noted_at": "2026-03-05T10:00:00",
            "reference_title": True,
        }

        # Act
        result = await LowMotivationSkill().generate(self._make_ctx(note_quote=quote))

        # Assert: 原文引用 + 出处 + explainability 标记（供路由层记录使用）
        self.assertIn("坚持从来不是在你想做的时候去做", result.body)
        self.assertIn("《读书笔记》", result.body)
        self.assertEqual(result.explainability.get("note_quote", {}).get("note_id"), 7)
        self.assertIn("引用了你自己的笔记", result.explainability.get("signals", []))

    async def test_low_motivation_skill_without_quote_keeps_body_clean(self):
        # Act
        result = await LowMotivationSkill().generate(self._make_ctx(note_quote=None))

        # Assert
        self.assertNotIn("还记得", result.body)
        self.assertNotIn("note_quote", result.explainability or {})


if __name__ == "__main__":
    unittest.main()
