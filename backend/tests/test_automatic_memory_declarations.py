"""Regression coverage for auditable automatic memory declarations."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.services.agent_long_memory_service import (
    STAGED,
    confirm_memory_candidate,
    ignore_memory_candidate,
    upsert_agent_memory,
)
from app.services.memory_service import _upsert_reflection_memories, upsert_user_memories_from_turn


class AutomaticMemoryDeclarationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "automatic_memory_declarations.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
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
        return user_id

    async def _declaration_for(self, user_id: int, memory_key: str) -> MemoryDeclaration:
        async with self.sessionmaker() as session:
            memory = (
                await session.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.memory_key == memory_key,
                    )
                )
            ).scalar_one()
            return (
                await session.execute(
                    select(MemoryDeclaration).where(MemoryDeclaration.memory_id == memory.id)
                )
            ).scalar_one()

    async def test_chat_extraction_records_a_staged_redacted_model_declaration(self):
        user_id = await self._create_user("automatic_chat")
        facts = [{
            "memory_key": "preferred_style",
            "memory_value": "偏好先给简短步骤。",
            "category": "style",
            "confidence": 0.82,
        }]

        async with self.sessionmaker() as session:
            with patch("app.services.memory_service._extract_facts_with_llm", AsyncMock(return_value=facts)):
                await upsert_user_memories_from_turn(
                    14,
                    "我喜欢先看简短步骤，再看细节。",
                    "明白。",
                    session,
                    user_id=user_id,
                )
            await session.commit()

        declaration = await self._declaration_for(user_id, "preferred_style")
        self.assertEqual(declaration.created_by, "model")
        self.assertEqual(declaration.review_status, "staged")
        self.assertEqual(declaration.source_type, "chat_turn")
        self.assertEqual(declaration.source_id, "conversation:14:preferred_style")
        self.assertNotIn("user_excerpt", json.dumps(json.loads(declaration.evidence), ensure_ascii=False))

    async def test_reflection_candidate_records_a_staged_model_declaration(self):
        user_id = await self._create_user("automatic_reflection")
        async with self.sessionmaker() as session:
            await _upsert_reflection_memories(
                [{
                    "memory_key": "focus_pattern",
                    "memory_value": "复盘时更容易发现薄弱点。",
                    "category": "pattern",
                    "confidence": 0.7,
                }],
                conversation_id=27,
                material_ids=[8],
                db=session,
                user_id=user_id,
            )
            await session.commit()

        declaration = await self._declaration_for(user_id, "focus_pattern")
        self.assertEqual(declaration.created_by, "model")
        self.assertEqual(declaration.review_status, "staged")
        self.assertEqual(declaration.source_type, "conversation_reflection")
        self.assertIn("conversation_reflection", declaration.evidence)

    async def test_chat_extraction_does_not_create_a_conflicting_candidate_for_a_locked_memory(self):
        user_id = await self._create_user("automatic_locked")
        async with self.sessionmaker() as session:
            session.add(
                UserMemory(
                    user_id=user_id,
                    memory_key="preferred_style",
                    memory_value="人工确认：先给短步骤。",
                    category="style",
                    status="active",
                    review_status="confirmed",
                    is_locked=1,
                )
            )
            await session.commit()

        facts = [{
            "memory_key": "preferred_style",
            "memory_value": "自动候选：给出长解释。",
            "category": "style",
            "confidence": 0.7,
        }]
        async with self.sessionmaker() as session:
            with patch("app.services.memory_service._extract_facts_with_llm", AsyncMock(return_value=facts)):
                await upsert_user_memories_from_turn(21, "我想要解释", "好的", session, user_id=user_id)
            await session.commit()

        async with self.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.memory_key == "preferred_style",
                    )
                )
            ).scalars().all()
            declarations = (
                await session.execute(
                    select(MemoryDeclaration).where(MemoryDeclaration.user_id == user_id)
                )
            ).scalars().all()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].memory_value, "人工确认：先给短步骤。")
        self.assertEqual(declarations, [])

    async def test_agent_candidate_tracks_review_decisions_and_prior_versions(self):
        user_id = await self._create_user("automatic_agent")
        async with self.sessionmaker() as session:
            candidate = await upsert_agent_memory(
                session,
                user_id,
                memory_key="event_signal",
                memory_value="用户近期更常完成复习任务。",
                category="pattern",
                confidence=0.7,
                review_status=STAGED,
                source_type="learning_event",
                source_id="42",
                evidence=[{"event_id": 42, "event_type": "review.completed"}],
            )
            ignored_candidate = await upsert_agent_memory(
                session,
                user_id,
                memory_key="event_signal_ignored",
                memory_value="用户可能需要更长学习时段。",
                category="pattern",
                confidence=0.6,
                review_status=STAGED,
                source_type="learning_event",
                source_id="43",
                evidence=[{"event_id": 43}],
            )
            await session.commit()

        async with self.sessionmaker() as session:
            await confirm_memory_candidate(session, user_id, int(candidate.id), lock=False)
            await ignore_memory_candidate(session, user_id, int(ignored_candidate.id))
            await upsert_agent_memory(
                session,
                user_id,
                memory_key="event_signal",
                memory_value="用户近期连续完成复习任务。",
                category="pattern",
                confidence=0.78,
                review_status=STAGED,
                source_type="learning_event",
                source_id="42",
                evidence=[{"event_id": 42, "event_type": "review.completed"}],
            )
            await session.commit()

        async with self.sessionmaker() as session:
            candidate_rows = (
                await session.execute(
                    select(MemoryDeclaration)
                    .where(MemoryDeclaration.user_id == user_id, MemoryDeclaration.memory_id == candidate.id)
                    .order_by(MemoryDeclaration.id)
                )
            ).scalars().all()
            ignored_row = (
                await session.execute(
                    select(MemoryDeclaration).where(
                        MemoryDeclaration.user_id == user_id,
                        MemoryDeclaration.memory_id == ignored_candidate.id,
                    )
                )
            ).scalar_one()

        self.assertEqual(candidate_rows[0].review_status, "superseded")
        self.assertEqual(candidate_rows[0].source_event_id, 42)
        self.assertIsNotNone(candidate_rows[0].valid_to)
        self.assertEqual(candidate_rows[1].review_status, STAGED)
        self.assertEqual(candidate_rows[1].supersedes_id, candidate_rows[0].id)
        self.assertEqual(ignored_row.review_status, "ignored")
        self.assertIsNotNone(ignored_row.valid_to)


if __name__ == "__main__":
    unittest.main()
