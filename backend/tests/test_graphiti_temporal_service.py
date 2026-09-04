"""Stage 7 Graphiti Temporal / Episodic Slice contract tests."""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.services.graphiti_shadow_service import graphiti_group_id
from app.services.graphiti_temporal_service import GraphitiTemporalService
from app.utils.utc import utc_now_db


class _FakeDriver:
    def __init__(self, *, projected_edges: int = 0, error: Exception | None = None):
        self.graph_operations_interface = None
        self.provider = None
        self.projected_edges = int(projected_edges)
        self.error = error
        self.calls: list[tuple[str, dict]] = []
        self.health_calls = 0

    async def health_check(self):
        self.health_calls += 1
        if self.error is not None:
            raise self.error
        return True

    async def execute_query(self, query: str, **kwargs):
        self.calls.append((str(query), dict(kwargs)))
        if self.error is not None:
            raise self.error
        if "projected_edges" in str(query):
            return ([{"projected_edges": self.projected_edges}], None, None)
        return ([], None, None)


class _FakeGraph:
    def __init__(self, *, search_edges=None, projected_edges: int = 0, error=None):
        self.driver = _FakeDriver(projected_edges=projected_edges, error=error)
        self.search_edges = list(search_edges or [])
        self.search_calls: list[dict] = []
        self.build_calls = 0
        self.closed = False

    async def build_indices_and_constraints(self):
        self.build_calls += 1
        if self.driver.error is not None:
            raise self.driver.error

    async def search_(self, query: str, *, config, group_ids):
        if self.driver.error is not None:
            raise self.driver.error
        self.search_calls.append(
            {
                "query": str(query),
                "group_ids": list(group_ids),
                "limit": int(config.limit),
            }
        )
        return SimpleNamespace(edges=list(self.search_edges))

    async def close(self):
        self.closed = True


class GraphitiTemporalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'graphiti-temporal.db'}"
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
            status="active",
            review_status="confirmed",
            category="goal",
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
        valid_from,
        valid_to=None,
        review_status: str = "confirmed",
        fact_key: str = "learning:focus",
    ) -> MemoryDeclaration:
        row = MemoryDeclaration(
            user_id=int(user_id),
            memory_id=int(memory_id),
            subject="user",
            predicate="learning_focus",
            fact_key=fact_key,
            value=value,
            valid_from=valid_from,
            valid_to=valid_to,
            observed_at=valid_from,
            confidence=1.0,
            review_status=review_status,
            source_type="manual",
            created_by="user",
        )
        db.add(row)
        await db.flush()
        return row

    async def test_rebuild_ingests_only_reviewed_owner_declarations_without_model_calls(self):
        async with self.sessions() as db:
            owner = await self._user(db, "temporal-owner")
            stranger = await self._user(db, "temporal-stranger")
            memory = await self._memory(db, user_id=owner.id, key="learning_focus")
            foreign_memory = await self._memory(db, user_id=stranger.id, key="learning_focus")
            now = utc_now_db()
            old = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="Tool Calling",
                valid_from=now - timedelta(days=20),
                valid_to=now - timedelta(days=10),
                review_status="superseded",
            )
            current = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="Agent Runtime",
                valid_from=now - timedelta(days=10),
            )
            await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="Unreviewed LangGraph",
                valid_from=now,
                review_status="staged",
                fact_key="learning:future-focus",
            )
            await self._declaration(
                db,
                user_id=stranger.id,
                memory_id=foreign_memory.id,
                value="Private foreign fact",
                valid_from=now,
            )
            await db.commit()

            graph = _FakeGraph()
            service = GraphitiTemporalService(db, graph=graph)
            result = await service.rebuild_user(user_id=int(owner.id))

            self.assertEqual(result["declarations"], 2)
            self.assertEqual(result["external_model_calls"], 0)
            self.assertEqual(result["embedding_calls"], 0)
            self.assertEqual(result["configured_model_cost"], 0.0)
            self.assertFalse(result["raw_episode_storage"])
            self.assertEqual(graph.build_calls, 1)

            edge_payloads = [
                kwargs["edge_data"]
                for _query, kwargs in graph.driver.calls
                if isinstance(kwargs.get("edge_data"), dict)
                and kwargs["edge_data"].get("mnemox_kind") == "temporal_declaration"
            ]
            self.assertEqual(len(edge_payloads), 2)
            self.assertEqual(
                {int(row["declaration_id"]) for row in edge_payloads},
                {int(old.id), int(current.id)},
            )
            serialized = repr(edge_payloads)
            self.assertNotIn("Unreviewed LangGraph", serialized)
            self.assertNotIn("Private foreign fact", serialized)
            self.assertTrue(
                all(row["group_id"] == graphiti_group_id(int(owner.id)) for row in edge_payloads)
            )

    async def test_current_and_historical_queries_rehydrate_from_sql(self):
        async with self.sessions() as db:
            owner = await self._user(db, "temporal-query-owner")
            memory = await self._memory(db, user_id=owner.id, key="learning_focus")
            now = utc_now_db()
            old = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="Tool Calling",
                valid_from=now - timedelta(days=20),
                valid_to=now - timedelta(days=10),
                review_status="superseded",
            )
            current = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="Agent Runtime",
                valid_from=now - timedelta(days=10),
            )
            await db.commit()
            group = graphiti_group_id(int(owner.id))
            edges = [
                SimpleNamespace(
                    group_id=group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(old.id)}"],
                    valid_at=(now - timedelta(days=20)).replace(tzinfo=timezone.utc),
                    invalid_at=(now - timedelta(days=10)).replace(tzinfo=timezone.utc),
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(current.id)}"],
                    valid_at=(now - timedelta(days=10)).replace(tzinfo=timezone.utc),
                    invalid_at=None,
                    expired_at=None,
                ),
            ]
            service = GraphitiTemporalService(db, graph=_FakeGraph(search_edges=edges))

            current_result = await service.query(
                user_id=int(owner.id),
                query="learning focus agent runtime tool calling",
                as_of=now.replace(tzinfo=timezone.utc),
            )
            historical = await service.query(
                user_id=int(owner.id),
                query="learning focus tool calling agent runtime",
                as_of=(now - timedelta(days=15)).replace(tzinfo=timezone.utc),
            )

            self.assertEqual(current_result["results"][0]["declaration_id"], int(current.id))
            self.assertEqual(current_result["results"][0]["value"], "Agent Runtime")
            self.assertEqual(historical["results"][0]["declaration_id"], int(old.id))
            self.assertEqual(historical["results"][0]["value"], "Tool Calling")
            self.assertEqual(current_result["runtime"]["external_model_calls"], 0)
            self.assertEqual(current_result["runtime"]["embedding_calls"], 0)

    async def test_query_rejects_foreign_unmapped_and_sql_stale_edges(self):
        async with self.sessions() as db:
            owner = await self._user(db, "temporal-filter-owner")
            stranger = await self._user(db, "temporal-filter-stranger")
            memory = await self._memory(db, user_id=owner.id, key="learning_focus")
            foreign_memory = await self._memory(db, user_id=stranger.id, key="learning_focus")
            now = utc_now_db()
            owner_row = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="LangGraph",
                valid_from=now - timedelta(days=1),
            )
            foreign_row = await self._declaration(
                db,
                user_id=stranger.id,
                memory_id=foreign_memory.id,
                value="Private",
                valid_from=now - timedelta(days=1),
            )
            await db.commit()
            owner_group = graphiti_group_id(int(owner.id))
            edges = [
                SimpleNamespace(
                    group_id=graphiti_group_id(int(stranger.id)),
                    episodes=[f"mnemox-memory-declaration-{int(stranger.id)}-{int(foreign_row.id)}"],
                    valid_at=now.replace(tzinfo=timezone.utc) - timedelta(days=1),
                    invalid_at=None,
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=owner_group,
                    episodes=["not-a-mnemox-episode"],
                    valid_at=now.replace(tzinfo=timezone.utc) - timedelta(days=1),
                    invalid_at=None,
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=owner_group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(owner_row.id)}"],
                    valid_at=now.replace(tzinfo=timezone.utc) - timedelta(days=1),
                    invalid_at=None,
                    expired_at=None,
                ),
            ]
            owner_row.review_status = "staged"
            await db.commit()
            service = GraphitiTemporalService(db, graph=_FakeGraph(search_edges=edges))
            result = await service.query(
                user_id=int(owner.id),
                query="learning focus",
                as_of=now.replace(tzinfo=timezone.utc),
            )

            self.assertEqual(result["status"], "no_result")
            self.assertEqual(result["results"], [])
            self.assertGreaterEqual(result["runtime"]["filtered_edges"], 1)
            self.assertEqual(result["runtime"]["unmapped_edges"], 1)
            self.assertNotIn("Private", repr(result))

    async def test_fact_key_narrowing_is_applied_during_sql_rehydrate(self):
        async with self.sessions() as db:
            owner = await self._user(db, "temporal-fact-key-owner")
            memory = await self._memory(db, user_id=owner.id, key="learning_focus")
            now = utc_now_db()
            focus = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="LangGraph",
                valid_from=now - timedelta(days=1),
                fact_key="learning:focus",
            )
            second_memory = await self._memory(db, user_id=owner.id, key="career_goal")
            career = await self._declaration(
                db,
                user_id=owner.id,
                memory_id=second_memory.id,
                value="AI Engineer",
                valid_from=now - timedelta(days=1),
                fact_key="career:goal",
            )
            await db.commit()
            group = graphiti_group_id(int(owner.id))
            edges = [
                SimpleNamespace(
                    group_id=group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(focus.id)}"],
                    valid_at=now.replace(tzinfo=timezone.utc) - timedelta(days=1),
                    invalid_at=None,
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(career.id)}"],
                    valid_at=now.replace(tzinfo=timezone.utc) - timedelta(days=1),
                    invalid_at=None,
                    expired_at=None,
                ),
            ]
            service = GraphitiTemporalService(db, graph=_FakeGraph(search_edges=edges))
            result = await service.query(
                user_id=int(owner.id),
                query="goal focus",
                fact_key="career:goal",
                as_of=now.replace(tzinfo=timezone.utc),
            )
            self.assertEqual([row["declaration_id"] for row in result["results"]], [int(career.id)])

    async def test_delete_and_status_are_group_scoped_and_payload_free(self):
        async with self.sessions() as db:
            owner = await self._user(db, "temporal-status-owner")
            memory = await self._memory(db, user_id=owner.id, key="learning_focus")
            now = utc_now_db()
            await self._declaration(
                db,
                user_id=owner.id,
                memory_id=memory.id,
                value="Graphiti",
                valid_from=now,
            )
            await db.commit()
            graph = _FakeGraph(projected_edges=1)
            service = GraphitiTemporalService(db, graph=graph)

            status = await service.status(user_id=int(owner.id))
            deleted = await service.delete_user_projection(user_id=int(owner.id))

            self.assertTrue(status["ok"])
            self.assertTrue(status["caught_up"])
            self.assertEqual(status["reviewed_declarations"], 1)
            self.assertEqual(status["projected_edges"], 1)
            self.assertEqual(status["external_model_calls"], 0)
            self.assertTrue(deleted["deleted"])
            self.assertNotIn("Graphiti", repr(status))
            group = graphiti_group_id(int(owner.id))
            delete_calls = [
                kwargs
                for query, kwargs in graph.driver.calls
                if "DETACH DELETE" in query
            ]
            self.assertTrue(delete_calls)
            self.assertEqual(delete_calls[-1]["params"]["group_id"], group)

    async def test_status_failure_reports_type_only(self):
        async with self.sessions() as db:
            owner = await self._user(db, "temporal-status-failure")
            graph = _FakeGraph(error=RuntimeError("PRIVATE GRAPH PASSWORD OR QUERY"))
            service = GraphitiTemporalService(db, graph=graph)
            status = await service.status(user_id=int(owner.id))
            self.assertFalse(status["ok"])
            self.assertEqual(status["error_type"], "RuntimeError")
            self.assertNotIn("PRIVATE GRAPH PASSWORD OR QUERY", repr(status))


if __name__ == "__main__":
    unittest.main()
