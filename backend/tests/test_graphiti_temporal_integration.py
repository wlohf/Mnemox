"""Real Graphiti 0.30.x + Neo4j integration for the Stage 7 Temporal Slice.

Run explicitly with a disposable/test Neo4j instance:

    RUN_GRAPHITI_TEMPORAL_INTEGRATION=1 \
    MNEMOX_TEST_NEO4J_URI=bolt://127.0.0.1:17687 \
    MNEMOX_TEST_NEO4J_USER=neo4j \
    MNEMOX_TEST_NEO4J_PASSWORD=... \
    PYTHONPATH=. venv/bin/python -m pytest -q tests/test_graphiti_temporal_integration.py

The production service itself installs fail-closed LLM/embedder/reranker clients,
so a passing test proves the bounded slice is model-free.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.services.graphiti_temporal_service import GraphitiTemporalService


RUN = os.getenv("RUN_GRAPHITI_TEMPORAL_INTEGRATION", "").strip() == "1"
HAS_GRAPHITI = importlib.util.find_spec("graphiti_core") is not None
NEO4J_URI = os.getenv("MNEMOX_TEST_NEO4J_URI", "").strip()
NEO4J_USER = os.getenv("MNEMOX_TEST_NEO4J_USER", "neo4j").strip()
NEO4J_PASSWORD = os.getenv("MNEMOX_TEST_NEO4J_PASSWORD", "").strip()
NEO4J_DATABASE = os.getenv("MNEMOX_TEST_NEO4J_DATABASE", "neo4j").strip()


@unittest.skipUnless(
    RUN and HAS_GRAPHITI and NEO4J_URI and NEO4J_PASSWORD,
    "requires explicit Graphiti Temporal integration environment",
)
class GraphitiTemporalIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'graphiti-temporal-real.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        row = User(
            username=name,
            email=f"{name}@example.test",
            hashed_password="hash",
        )
        db.add(row)
        await db.flush()
        return row

    async def _memory(self, db, *, user_id: int, key: str) -> UserMemory:
        row = UserMemory(
            user_id=int(user_id),
            memory_key=key,
            memory_value="current",
            category="goal",
            status="active",
            review_status="confirmed",
        )
        db.add(row)
        await db.flush()
        return row

    async def _declaration(
        self,
        db,
        *,
        user_id: int,
        memory_id: int,
        value: str,
        valid_from: datetime,
        valid_to: datetime | None,
        review_status: str,
        fact_key: str = "learning:focus",
    ) -> MemoryDeclaration:
        row = MemoryDeclaration(
            user_id=int(user_id),
            memory_id=int(memory_id),
            subject="user",
            predicate="learning_focus",
            fact_key=fact_key,
            value=value,
            valid_from=valid_from.replace(tzinfo=None),
            valid_to=valid_to.replace(tzinfo=None) if valid_to else None,
            observed_at=valid_from.replace(tzinfo=None),
            confidence=1.0,
            review_status=review_status,
            source_type="manual",
            created_by="user",
        )
        db.add(row)
        await db.flush()
        return row

    async def test_real_temporal_slice_current_asof_isolation_delete_and_rebuild(self):
        sep01 = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
        sep10 = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
        sep20 = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
        sep25 = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)

        with (
            patch.object(settings, "NEO4J_URI", NEO4J_URI),
            patch.object(settings, "NEO4J_USER", NEO4J_USER),
            patch.object(settings, "NEO4J_PASSWORD", NEO4J_PASSWORD),
            patch.object(settings, "NEO4J_DATABASE", NEO4J_DATABASE),
        ):
            async with self.sessions() as db:
                owner = await self._user(db, "graphiti-stage7-owner")
                stranger = await self._user(db, "graphiti-stage7-stranger")
                owner_memory = await self._memory(
                    db,
                    user_id=owner.id,
                    key="learning_focus",
                )
                foreign_memory = await self._memory(
                    db,
                    user_id=stranger.id,
                    key="learning_focus",
                )
                tool = await self._declaration(
                    db,
                    user_id=owner.id,
                    memory_id=owner_memory.id,
                    value="Tool Calling",
                    valid_from=sep01,
                    valid_to=sep10,
                    review_status="superseded",
                )
                runtime = await self._declaration(
                    db,
                    user_id=owner.id,
                    memory_id=owner_memory.id,
                    value="Agent Runtime",
                    valid_from=sep10,
                    valid_to=sep20,
                    review_status="superseded",
                )
                langgraph = await self._declaration(
                    db,
                    user_id=owner.id,
                    memory_id=owner_memory.id,
                    value="LangGraph",
                    valid_from=sep20,
                    valid_to=None,
                    review_status="confirmed",
                )
                await self._declaration(
                    db,
                    user_id=owner.id,
                    memory_id=owner_memory.id,
                    value="Unreviewed Future Focus",
                    valid_from=sep25,
                    valid_to=None,
                    review_status="staged",
                    fact_key="learning:future-focus",
                )
                await self._declaration(
                    db,
                    user_id=stranger.id,
                    memory_id=foreign_memory.id,
                    value="Private Foreign Focus",
                    valid_from=sep01,
                    valid_to=None,
                    review_status="confirmed",
                )
                await db.commit()

                owner_service = GraphitiTemporalService(db)
                foreign_service = GraphitiTemporalService(db)
                try:
                    owner_rebuild = await owner_service.rebuild_user(user_id=int(owner.id))
                    foreign_rebuild = await foreign_service.rebuild_user(user_id=int(stranger.id))

                    self.assertEqual(owner_rebuild["declarations"], 3)
                    self.assertEqual(owner_rebuild["external_model_calls"], 0)
                    self.assertEqual(owner_rebuild["embedding_calls"], 0)
                    self.assertEqual(foreign_rebuild["declarations"], 1)

                    query = "learning focus Tool Calling Agent Runtime LangGraph Private Foreign"
                    on_sep05 = await owner_service.query(
                        user_id=int(owner.id),
                        query=query,
                        fact_key="learning:focus",
                        as_of=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
                    )
                    on_sep15 = await owner_service.query(
                        user_id=int(owner.id),
                        query=query,
                        fact_key="learning:focus",
                        as_of=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
                    )
                    on_sep25 = await owner_service.query(
                        user_id=int(owner.id),
                        query=query,
                        fact_key="learning:focus",
                        as_of=sep25,
                    )

                    self.assertEqual(
                        [row["declaration_id"] for row in on_sep05["results"]],
                        [int(tool.id)],
                    )
                    self.assertEqual(on_sep05["results"][0]["value"], "Tool Calling")
                    self.assertEqual(
                        [row["declaration_id"] for row in on_sep15["results"]],
                        [int(runtime.id)],
                    )
                    self.assertEqual(on_sep15["results"][0]["value"], "Agent Runtime")
                    self.assertEqual(
                        [row["declaration_id"] for row in on_sep25["results"]],
                        [int(langgraph.id)],
                    )
                    self.assertEqual(on_sep25["results"][0]["value"], "LangGraph")
                    self.assertNotIn("Private Foreign Focus", repr(on_sep05))
                    self.assertNotIn("Private Foreign Focus", repr(on_sep15))
                    self.assertNotIn("Private Foreign Focus", repr(on_sep25))
                    self.assertNotIn("Unreviewed Future Focus", repr(on_sep25))

                    status = await owner_service.status(user_id=int(owner.id))
                    self.assertTrue(status["ok"])
                    self.assertTrue(status["caught_up"])
                    self.assertEqual(status["reviewed_declarations"], 3)
                    self.assertEqual(status["projected_edges"], 3)
                    self.assertEqual(status["external_model_calls"], 0)

                    deleted = await owner_service.delete_user_projection(user_id=int(owner.id))
                    self.assertTrue(deleted["deleted"])
                    after_delete = await owner_service.status(user_id=int(owner.id))
                    self.assertTrue(after_delete["ok"])
                    self.assertFalse(after_delete["caught_up"])
                    self.assertEqual(after_delete["projected_edges"], 0)

                    rebuilt_again = await owner_service.rebuild_user(user_id=int(owner.id))
                    self.assertEqual(rebuilt_again["declarations"], 3)
                    restored = await owner_service.status(user_id=int(owner.id))
                    self.assertTrue(restored["caught_up"])
                finally:
                    await owner_service.delete_user_projection(user_id=int(owner.id))
                    await foreign_service.delete_user_projection(user_id=int(stranger.id))
                    await owner_service.close()
                    await foreign_service.close()


if __name__ == "__main__":
    unittest.main()
