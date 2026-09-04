import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.note import Note
from app.models.question import ReviewSchedule, WrongQuestion
from app.models.user import User
from app.models.user_profile import UserProfile
from app.services.weekly_learning_report_service import build_weekly_learning_report


class WeeklyLearningReportServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        database_path = Path(self.tmpdir.name) / "weekly_report.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessions() as session:
            user = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
        return user_id

    async def test_draft_is_stable_user_scoped_and_copy_only(self):
        owner_id = await self._create_user("weekly-owner")
        other_id = await self._create_user("weekly-other")
        now = datetime(2026, 9, 3, 12, 0, 0)
        observed = now - timedelta(hours=2)
        async with self.sessions() as session:
            session.add_all([
                Note(
                    user_id=owner_id,
                    title="矩阵复习摘要",
                    content="特征值与特征向量需要继续用例题巩固。",
                    created_at=observed,
                    updated_at=observed,
                ),
                Note(
                    user_id=owner_id,
                    title="双链笔记",
                    content="来自 vault 的原始摘录。",
                    source_path="math/linear-algebra.md",
                    source_vault_id="vault-1",
                    source_file_id="file-1",
                    source_sync_state="active",
                    created_at=observed,
                    updated_at=observed,
                ),
                Note(
                    user_id=owner_id,
                    title="冲突笔记",
                    content="冲突版本只允许读取。",
                    source_path="math/conflict.md",
                    source_vault_id="vault-1",
                    source_file_id="file-2",
                    source_sync_state="conflict",
                    created_at=observed,
                    updated_at=observed,
                ),
                Note(
                    user_id=owner_id,
                    title="已从 vault 消失",
                    content="不应进入草案。",
                    source_path="missing.md",
                    source_sync_state="missing",
                    created_at=observed,
                    updated_at=observed,
                ),
                Note(
                    user_id=other_id,
                    title="其他用户的笔记",
                    content="绝不能泄露。",
                    created_at=observed,
                    updated_at=observed,
                ),
                ReviewSchedule(
                    user_id=owner_id,
                    item_type="chapter",
                    item_id=8,
                    status="completed",
                    completed_at=observed,
                    interval_days=3,
                    last_quality=4,
                    is_archived=False,
                ),
                WrongQuestion(
                    user_id=owner_id,
                    question_id=801,
                    knowledge_point="矩阵对角化",
                    wrong_count=2,
                    mastery_status="partial",
                    last_wrong_at=observed,
                    created_at=observed,
                ),
            ])
            await session.commit()

        async with self.sessions() as session:
            first = await build_weekly_learning_report(session, owner_id, now=now)
            second = await build_weekly_learning_report(session, owner_id, now=now)
            profile_count = int(
                (await session.execute(select(func.count(UserProfile.user_id)))).scalar_one()
            )

        first_draft = first["consolidation"]
        second_draft = second["consolidation"]
        self.assertEqual(first_draft["draft_key"], second_draft["draft_key"])
        self.assertEqual(first_draft["markdown"], second_draft["markdown"])
        self.assertEqual(first_draft["source_counts"], {
            "notes": 3,
            "reviews": 1,
            "wrong_questions": 1,
            "total": 5,
        })
        self.assertEqual(profile_count, 0)
        self.assertFalse(first_draft["write_policy"]["automatic_write"])
        self.assertFalse(first_draft["write_policy"]["obsidian_write_allowed"])
        self.assertEqual(first_draft["write_policy"]["imported_source_count"], 2)
        ownership = {source["ownership"] for source in first_draft["sources"]}
        self.assertEqual(ownership, {"mnemox", "obsidian_read_only", "obsidian_conflict"})
        self.assertNotIn("其他用户的笔记", first_draft["markdown"])
        self.assertNotIn("已从 vault 消失", first_draft["markdown"])
        self.assertIn("不会自动创建笔记或回写 Obsidian", first_draft["markdown"])

        async with self.sessions() as session:
            note = (
                await session.execute(
                    select(Note).where(Note.user_id == owner_id, Note.title == "矩阵复习摘要")
                )
            ).scalar_one()
            note.content = "加入一个新的矩阵例题，来源版本已经变化。"
            note.updated_at = now - timedelta(minutes=30)
            await session.commit()
        async with self.sessions() as session:
            changed = await build_weekly_learning_report(session, owner_id, now=now)

        self.assertNotEqual(first_draft["draft_key"], changed["consolidation"]["draft_key"])

    async def test_scan_uses_the_learners_local_natural_week(self):
        user_id = await self._create_user("weekly-time-zone")
        now = datetime(2026, 9, 1, 16, 30, 0)
        async with self.sessions() as session:
            session.add_all([
                Note(
                    user_id=user_id,
                    title="上海周一范围内",
                    content="应被扫描。",
                    created_at=datetime(2026, 8, 30, 17, 0, 0),
                    updated_at=datetime(2026, 8, 30, 17, 0, 0),
                ),
                Note(
                    user_id=user_id,
                    title="上海上周范围",
                    content="不应被扫描。",
                    created_at=datetime(2026, 8, 30, 15, 59, 59),
                    updated_at=datetime(2026, 8, 30, 15, 59, 59),
                ),
            ])
            await session.commit()

        async with self.sessions() as session:
            report = await build_weekly_learning_report(
                session,
                user_id,
                time_zone="Asia/Shanghai",
                now=now,
            )

        draft = report["consolidation"]
        self.assertEqual(report["time_zone"], "Asia/Shanghai")
        self.assertEqual(draft["week_start"], "2026-08-31")
        self.assertEqual(draft["week_end_exclusive"], "2026-09-07")
        self.assertEqual(draft["scan_start_utc"], "2026-08-30T16:00:00Z")
        self.assertEqual(draft["scan_end_utc"], "2026-09-01T16:30:00Z")
        self.assertTrue(draft["scan_end_inclusive"])
        self.assertEqual(draft["source_counts"]["notes"], 1)
        self.assertIn("上海周一范围内", draft["markdown"])
        self.assertNotIn("上海上周范围", draft["markdown"])


if __name__ == "__main__":
    unittest.main()
