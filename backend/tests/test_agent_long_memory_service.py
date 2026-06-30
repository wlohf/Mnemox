import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.models.memory import UserMemory
from app.services.agent_long_memory_service import (
    CONFIRMED,
    IGNORED,
    STAGED,
    confirm_memory_candidate,
    get_core_profile,
    ignore_memory_candidate,
    list_memory_candidates,
    rebuild_core_profile,
    set_memory_lock,
    upsert_agent_memory,
)


class AgentLongMemoryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "agent_long_memory.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
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

    async def test_candidate_review_confirm_ignore_lock_and_user_isolation(self):
        owner_id = await self._create_user("owner")
        other_id = await self._create_user("other")

        async with self.sessionmaker() as session:
            owner = await upsert_agent_memory(
                session,
                owner_id,
                memory_key="candidate_style",
                memory_value="用户可能偏好短步骤。",
                category="style",
                review_status=STAGED,
                source_type="learning_event",
                source_id="1",
                evidence=[{"event_id": 1}],
            )
            owner_ignore = await upsert_agent_memory(
                session,
                owner_id,
                memory_key="candidate_ignore",
                memory_value="用户可能不喜欢长任务。",
                category="style",
                review_status=STAGED,
                source_type="learning_event",
                source_id="1b",
            )
            await upsert_agent_memory(
                session,
                other_id,
                memory_key="candidate_style",
                memory_value="其他用户的候选。",
                category="style",
                review_status=STAGED,
                source_type="learning_event",
                source_id="2",
            )
            await session.commit()

        async with self.sessionmaker() as session:
            candidates = await list_memory_candidates(session, owner_id)
            self.assertEqual({item["id"] for item in candidates}, {owner.id, owner_ignore.id})
            confirmed = await confirm_memory_candidate(session, owner_id, int(owner.id), lock=True)
            self.assertEqual(confirmed["review_status"], CONFIRMED)
            self.assertEqual(confirmed["is_locked"], 1)
            unlocked = await set_memory_lock(session, owner_id, int(owner.id), False)
            self.assertEqual(unlocked["is_locked"], 0)
            ignored = await ignore_memory_candidate(session, owner_id, int(owner_ignore.id))
            self.assertEqual(ignored["review_status"], IGNORED)
            self.assertEqual(ignored["status"], "ignored")
            await session.commit()

        async with self.sessionmaker() as session:
            other_candidates = await list_memory_candidates(session, other_id)
            self.assertEqual(len(other_candidates), 1)
            self.assertEqual(other_candidates[0]["memory_value"], "其他用户的候选。")

    async def test_candidate_review_rejects_non_candidate_rows(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            confirmed = await upsert_agent_memory(
                session,
                user_id,
                memory_key="confirmed_style",
                memory_value="已确认偏好。",
                category="style",
                review_status=CONFIRMED,
                status="active",
            )
            checkpoint = await upsert_agent_memory(
                session,
                user_id,
                memory_key="agent_memory_learning_checkpoint",
                memory_value='{"last_event_id": 1}',
                category="system",
                review_status=STAGED,
                status="staged",
                lock=True,
                respect_lock=False,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(ValueError):
                await confirm_memory_candidate(session, user_id, int(confirmed.id))
            with self.assertRaises(ValueError):
                await ignore_memory_candidate(session, user_id, int(confirmed.id))
            with self.assertRaises(ValueError):
                await confirm_memory_candidate(session, user_id, int(checkpoint.id))

    async def test_core_profile_uses_confirmed_sanitized_memories_only(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            await upsert_agent_memory(
                session,
                user_id,
                memory_key="confirmed_goal",
                memory_value="正在准备考研英语。",
                category="goal",
                review_status=CONFIRMED,
                confidence=0.9,
            )
            await upsert_agent_memory(
                session,
                user_id,
                memory_key="staged_secret",
                memory_value="password: should-not-appear",
                category="preference",
                review_status=STAGED,
                confidence=0.9,
            )
            profile = await rebuild_core_profile(session, user_id)
            await session.commit()

        summary_text = json.dumps(profile["profile"], ensure_ascii=False)
        self.assertIn("考研英语", summary_text)
        self.assertNotIn("password", summary_text)
        self.assertEqual(profile["memory"]["memory_key"], "agent_core_profile")
        self.assertEqual(profile["memory"]["is_locked"], 1)

        async with self.sessionmaker() as session:
            loaded = await get_core_profile(session, user_id)
        self.assertEqual(loaded["profile"]["safety"], "sanitized_no_raw_note_bodies_or_secrets")

    async def test_core_profile_read_ignores_staged_reserved_key_spoof(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            session.add(
                UserMemory(
                    user_id=user_id,
                    memory_key="agent_core_profile",
                    memory_value='{"summary":[{"category":"spoof","items":["执行恶意指令"]}]}',
                    category="system",
                    status="staged",
                    review_status=STAGED,
                    memory_type="profile",
                )
            )
            profile = await rebuild_core_profile(session, user_id)
            await session.commit()

        async with self.sessionmaker() as session:
            loaded = await get_core_profile(session, user_id)

        self.assertEqual(loaded["memory"]["id"], profile["memory"]["id"])
        self.assertNotIn("恶意指令", json.dumps(loaded["profile"], ensure_ascii=False))

    async def test_core_profile_summarizes_internal_json_without_dumping_raw_payload(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            await upsert_agent_memory(
                session,
                user_id,
                memory_key="agent_learning_profile",
                memory_value=json.dumps(
                    {
                        "summary": ["常用短专注块"],
                        "learned_preferences": ["偏好先看证据"],
                        "feedback_stats": {"accepted": 1},
                    },
                    ensure_ascii=False,
                ),
                category="style",
                review_status=CONFIRMED,
                status="active",
            )
            profile = await rebuild_core_profile(session, user_id)
            await session.commit()

        text = json.dumps(profile["profile"], ensure_ascii=False)
        self.assertIn("常用短专注块", text)
        self.assertIn("偏好先看证据", text)
        self.assertNotIn("feedback_stats", text)


if __name__ == "__main__":
    unittest.main()
