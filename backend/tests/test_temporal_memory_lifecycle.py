"""End-to-end coverage for canonical SQL temporal-memory lifecycle rules."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.routers.memory import (
    MemoryCorrectionRequest,
    MemoryCreateRequest,
    MemoryUpdateRequest,
    correct_memory,
    create_memory,
    delete_memory,
    expire_overdue_memories,
    get_memories,
    get_memory_conflicts,
    get_memory_declarations,
    update_memory,
)
from app.services.agent_long_memory_service import (
    CONFIRMED,
    STAGED,
    confirm_memory_candidate,
    get_core_profile,
    ignore_memory_candidate,
    rebuild_core_profile,
    upsert_agent_memory,
)
from app.services.context_store import L0, L1, L2, KeywordContextStore
from app.services.memory_declaration_service import expire_memory_facts
from app.services.memory_service import build_memory_prompt_fragment, get_relevant_memories
from app.services.retrieval_router import RetrievalRouter


class TemporalMemoryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        database_path = Path(self.tmpdir.name) / "temporal-memory.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> User:
        async with self.sessionmaker() as session:
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
        return User(
            id=user_id,
            username=username,
            email=f"{username}@example.com",
            hashed_password="hash",
            is_active=True,
        )

    async def _create_conflict(self, user: User) -> tuple[int, int]:
        async with self.sessionmaker() as session:
            current = await upsert_agent_memory(
                session,
                int(user.id),
                memory_key="current_learning_goal",
                memory_value="本周重点学习向量检索。",
                category="goal",
                review_status=CONFIRMED,
                source_type="learning_event",
                source_id="goal-original",
            )
            candidate = await upsert_agent_memory(
                session,
                int(user.id),
                memory_key="current_learning_goal",
                memory_value="本周重点学习工具调用。",
                category="goal",
                review_status=CONFIRMED,
                source_type="conversation_reflection",
                source_id="goal-replacement",
            )
            await session.commit()
        return int(current.id), int(candidate.id)

    async def test_contradictory_source_is_staged_and_does_not_replace_effective_fact(self):
        owner = await self._create_user("temporal_conflict")
        current_id, candidate_id = await self._create_conflict(owner)

        async with self.sessionmaker() as session:
            conflicts = await get_memory_conflicts(db=session, current_user=owner)
            visible = await get_relevant_memories(session, topic="学习", user_id=int(owner.id))
            memories = await get_memories(db=session, current_user=owner)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["fact_key"], "current_learning_goal")
        self.assertEqual(conflicts[0]["current_memory_id"], current_id)
        self.assertEqual(conflicts[0]["candidate_memory_id"], candidate_id)
        self.assertEqual(conflicts[0]["candidate"]["review_status"], STAGED)
        self.assertEqual([item["value"] for item in visible], ["本周重点学习向量检索。"])
        staged = next(item for item in memories if item["id"] == candidate_id)
        self.assertEqual(staged["conflicts_with_id"], conflicts[0]["current"]["id"])

    async def test_confirming_conflict_closes_prior_fact_and_keeps_cross_projection_history(self):
        owner = await self._create_user("temporal_confirm")
        current_id, candidate_id = await self._create_conflict(owner)

        async with self.sessionmaker() as session:
            confirmed = await confirm_memory_candidate(session, int(owner.id), candidate_id, lock=True)
            await session.commit()

        async with self.sessionmaker() as session:
            old_memory = await session.get(UserMemory, current_id)
            history = await get_memory_declarations(candidate_id, db=session, current_user=owner)
            conflicts = await get_memory_conflicts(db=session, current_user=owner)
            fragment = await build_memory_prompt_fragment(session, user_id=int(owner.id))

        self.assertEqual(confirmed["is_locked"], 1)
        self.assertEqual(old_memory.status, "superseded")
        self.assertEqual(len(history), 2)
        replacement, previous = history
        self.assertEqual(replacement["supersedes_id"], previous["id"])
        self.assertEqual(previous["review_status"], "superseded")
        self.assertEqual(previous["valid_to"], replacement["valid_from"])
        self.assertEqual(conflicts, [])
        self.assertIn("工具调用", fragment)
        self.assertNotIn("向量检索", fragment)

    async def test_rejecting_conflict_preserves_old_fact_and_records_user_reason(self):
        owner = await self._create_user("temporal_reject")
        current_id, candidate_id = await self._create_conflict(owner)

        async with self.sessionmaker() as session:
            rejected = await ignore_memory_candidate(
                session,
                int(owner.id),
                candidate_id,
                reason="inaccurate",
            )
            await session.commit()

        async with self.sessionmaker() as session:
            original = await session.get(UserMemory, current_id)
            declarations = await get_memory_declarations(candidate_id, db=session, current_user=owner)

        candidate = next(item for item in declarations if item["memory_id"] == candidate_id)
        self.assertEqual(rejected["review_status"], "inaccurate")
        self.assertEqual(original.status, "active")
        self.assertEqual(original.review_status, CONFIRMED)
        self.assertEqual(candidate["resolution_reason"], "inaccurate")
        self.assertIsNotNone(candidate["valid_to"])

    async def test_tentative_update_from_same_source_keeps_confirmed_projection(self):
        owner = await self._create_user("temporal_same_source")
        async with self.sessionmaker() as session:
            original = await upsert_agent_memory(
                session,
                int(owner.id),
                memory_key="explanation_style",
                memory_value="先给出结论。",
                category="style",
                review_status=CONFIRMED,
                source_type="learning_event",
                source_id="style-event",
            )
            tentative = await upsert_agent_memory(
                session,
                int(owner.id),
                memory_key="explanation_style",
                memory_value="先给出长篇背景。",
                category="style",
                review_status=STAGED,
                source_type="learning_event",
                source_id="style-event",
            )
            await session.commit()

        self.assertNotEqual(original.id, tentative.id)
        self.assertEqual(original.review_status, CONFIRMED)
        self.assertEqual(tentative.review_status, STAGED)

    async def test_expiration_closes_claim_excludes_all_reads_and_removes_derived_profile(self):
        owner = await self._create_user("temporal_expiration")
        async with self.sessionmaker() as session:
            memory = await upsert_agent_memory(
                session,
                int(owner.id),
                memory_key="temporary_goal",
                memory_value="临时复习 BM25。",
                category="goal",
                review_status=CONFIRMED,
                expires_at=datetime.now() + timedelta(hours=1),
            )
            profile = await rebuild_core_profile(session, int(owner.id))
            router = RetrievalRouter(session, material_backend=object(), context_store=object())
            hits = await router.search("BM25", user_id=int(owner.id), source_types=("memory",))
            memory_id = int(memory.id)
            profile_id = int(profile["memory"]["id"])
            memory.expires_at = datetime.now() - timedelta(minutes=5)
            await session.commit()

        async with self.sessionmaker() as session:
            fragment = await build_memory_prompt_fragment(session, user_id=int(owner.id))
            relevant = await get_relevant_memories(session, topic="BM25", user_id=int(owner.id))
            router = RetrievalRouter(session, material_backend=object(), context_store=object())
            loaded = await router.load_hit(hits[0], user_id=int(owner.id), level=L2)
            refreshed_profile = await get_core_profile(session, int(owner.id))
            expired_memory = await session.get(UserMemory, memory_id)
            removed_profile = await session.get(UserMemory, profile_id)
            history = await get_memory_declarations(memory_id, db=session, current_user=owner)

        self.assertEqual(fragment, "")
        self.assertEqual(relevant, [])
        self.assertEqual(loaded, "")
        self.assertIsNone(removed_profile)
        self.assertIsNone(refreshed_profile["memory"])
        self.assertEqual(expired_memory.status, "expired")
        self.assertEqual(history[0]["review_status"], "expired")
        self.assertEqual(history[0]["resolution_reason"], "expired_at_configured_deadline")
        self.assertIsNotNone(history[0]["valid_to"])

    async def test_keyword_context_store_rejects_expired_and_unconfirmed_memory_at_every_level(self):
        owner = await self._create_user("temporal_context_store")
        now = datetime.now()
        async with self.sessionmaker() as session:
            current = UserMemory(
                user_id=int(owner.id),
                memory_key="context_current",
                memory_value="向量检索当前有效事实。",
                status="active",
                review_status=CONFIRMED,
                expires_at=now + timedelta(hours=1),
            )
            expired = UserMemory(
                user_id=int(owner.id),
                memory_key="context_expired",
                memory_value="向量检索已经过期的事实。",
                status="active",
                review_status=CONFIRMED,
                expires_at=now - timedelta(minutes=1),
            )
            staged = UserMemory(
                user_id=int(owner.id),
                memory_key="context_staged",
                memory_value="向量检索尚未确认的推断。",
                status="active",
                review_status=STAGED,
            )
            ignored = UserMemory(
                user_id=int(owner.id),
                memory_key="context_ignored",
                memory_value="向量检索已经忽略的事实。",
                status="ignored",
                review_status=CONFIRMED,
            )
            session.add_all([current, expired, staged, ignored])
            await session.flush()
            current_id = int(current.id)
            hidden_ids = [int(expired.id), int(staged.id), int(ignored.id)]
            await session.commit()

        store = KeywordContextStore()
        async with self.sessionmaker() as session:
            visible = await store.retrieve(
                session,
                int(owner.id),
                "向量检索",
                source_types=("memory",),
            )
            hidden_content = [
                await store.load_tiered(session, int(owner.id), "memory", memory_id, level)
                for memory_id in hidden_ids
                for level in (L0, L1, L2)
            ]

        self.assertEqual([item.source_id for item in visible], [current_id])
        self.assertEqual(hidden_content, [""] * 9)

    async def test_manual_correction_records_reason_locks_fact_and_invalidates_profile(self):
        owner = await self._create_user("temporal_correction")
        async with self.sessionmaker() as session:
            original = await create_memory(
                MemoryCreateRequest(
                    memory_key="learning_preference",
                    memory_value="偏好视频课程。",
                    category="preference",
                ),
                db=session,
                current_user=owner,
            )
            await rebuild_core_profile(session, int(owner.id))
            await session.commit()

        async with self.sessionmaker() as session:
            corrected = await correct_memory(
                int(original["id"]),
                MemoryCorrectionRequest(
                    memory_value="偏好通过实际项目练习。",
                    reason="之前的推断不准确，我更喜欢动手实践。",
                ),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            history = await get_memory_declarations(int(original["id"]), db=session, current_user=owner)
            core_profile = await get_core_profile(session, int(owner.id))

        self.assertEqual(corrected["is_locked"], 1)
        self.assertEqual(history[0]["resolution_reason"], "之前的推断不准确，我更喜欢动手实践。")
        self.assertEqual(history[1]["review_status"], "superseded")
        self.assertEqual(history[0]["supersedes_id"], history[1]["id"])
        self.assertIn("动手实践", json.dumps(history[0], ensure_ascii=False))
        self.assertIsNone(core_profile["memory"])

    async def test_ignoring_and_restoring_fact_close_and_reopen_temporal_history(self):
        owner = await self._create_user("temporal_restore")
        async with self.sessionmaker() as session:
            original = await create_memory(
                MemoryCreateRequest(memory_key="restorable", memory_value="用户希望获得简洁回答。"),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            await update_memory(
                int(original["id"]),
                MemoryUpdateRequest(memory_value="用户希望获得简洁回答。", status="ignored"),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            restored = await update_memory(
                int(original["id"]),
                MemoryUpdateRequest(memory_value="用户希望获得简洁回答。", status="active"),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            history = await get_memory_declarations(int(original["id"]), db=session, current_user=owner)

        self.assertEqual(restored["review_status"], "confirmed")
        self.assertEqual([item["review_status"] for item in history], ["confirmed", "ignored"])
        self.assertIsNotNone(history[1]["valid_to"])

    async def test_delete_clears_derived_profile_and_conflict_reference_without_cross_user_loss(self):
        owner = await self._create_user("temporal_delete_owner")
        other = await self._create_user("temporal_delete_other")
        current_id, candidate_id = await self._create_conflict(owner)
        async with self.sessionmaker() as session:
            profile = await rebuild_core_profile(session, int(owner.id))
            other_memory = await create_memory(
                MemoryCreateRequest(memory_key="current_learning_goal", memory_value="其他用户的独立事实。"),
                db=session,
                current_user=other,
            )
            profile_id = int(profile["memory"]["id"])
            await session.commit()

        async with self.sessionmaker() as session:
            await delete_memory(current_id, db=session, current_user=owner)
            await session.commit()

        async with self.sessionmaker() as session:
            candidate = (
                await session.execute(
                    select(MemoryDeclaration).where(MemoryDeclaration.memory_id == candidate_id)
                )
            ).scalar_one()
            other_rows = await get_memory_declarations(int(other_memory["id"]), db=session, current_user=other)
            removed_profile = await session.get(UserMemory, profile_id)

        self.assertIsNone(candidate.conflicts_with_id)
        self.assertIsNone(removed_profile)
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["value"], "其他用户的独立事实。")

    async def test_expired_candidate_cannot_be_confirmed(self):
        owner = await self._create_user("temporal_expired_candidate")
        async with self.sessionmaker() as session:
            candidate = await upsert_agent_memory(
                session,
                int(owner.id),
                memory_key="temporary_candidate",
                memory_value="只在今天有效的推断。",
                review_status=STAGED,
                expires_at=datetime.now() - timedelta(minutes=1),
            )
            candidate_id = int(candidate.id)
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(ValueError):
                await confirm_memory_candidate(session, int(owner.id), candidate_id)
            await session.commit()

        async with self.sessionmaker() as session:
            history = await get_memory_declarations(candidate_id, db=session, current_user=owner)
        self.assertEqual(history[0]["review_status"], "expired")

    async def test_expiration_maintenance_and_conflicts_are_user_scoped(self):
        owner = await self._create_user("temporal_owner_scope")
        other = await self._create_user("temporal_other_scope")
        async with self.sessionmaker() as session:
            owner_memory = await upsert_agent_memory(
                session,
                int(owner.id),
                memory_key="scoped_expiry",
                memory_value="owner only",
                expires_at=datetime.now() - timedelta(minutes=2),
            )
            other_memory = await upsert_agent_memory(
                session,
                int(other.id),
                memory_key="scoped_expiry",
                memory_value="other only",
                expires_at=datetime.now() - timedelta(minutes=2),
            )
            await session.commit()

        async with self.sessionmaker() as session:
            expired = await expire_overdue_memories(db=session, current_user=owner)
            await session.commit()

        async with self.sessionmaker() as session:
            owner_row = await session.get(UserMemory, int(owner_memory.id))
            other_row = await session.get(UserMemory, int(other_memory.id))

        self.assertEqual(expired["memory_ids"], [int(owner_memory.id)])
        self.assertEqual(owner_row.status, "expired")
        self.assertEqual(other_row.status, "active")

    async def test_foreign_memory_correction_is_not_allowed(self):
        owner = await self._create_user("temporal_foreign_owner")
        other = await self._create_user("temporal_foreign_other")
        async with self.sessionmaker() as session:
            original = await create_memory(
                MemoryCreateRequest(memory_key="private_fact", memory_value="owner private"),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as error:
                await correct_memory(
                    int(original["id"]),
                    MemoryCorrectionRequest(memory_value="wrong", reason="cross-user"),
                    db=session,
                    current_user=other,
                )
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
