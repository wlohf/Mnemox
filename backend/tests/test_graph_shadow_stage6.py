"""Stage 6 Neo4j and Graphiti shadow safety gates."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
from datetime import timedelta, timezone
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    ClaimRelation,
    KnowledgeProjectionOutbox,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.services.graph_shadow_service import (
    compare_graphiti_temporal_shadow,
    compare_neo4j_claim_shadow,
    neo4j_projection_lag_summary,
)
from app.services.graph_store.base import GraphHit
from app.services.graph_store.factory import create_graph_store
from app.services.graph_store.neo4j_store import Neo4jGraphStore
from app.services.graph_store.sql_store import SqlGraphStore
from app.services.graphiti_shadow_service import (
    GraphitiShadowAdapter,
    create_graphiti_client,
    graphiti_group_id,
)
from app.services.knowledge_projection_service import (
    NEO4J_GRAPH_PROJECTION_TARGET,
    claim_next_knowledge_projection,
    enqueue_user_knowledge_rebuild,
    process_claimed_knowledge_projection,
)
from app.services.knowledge_projection_worker import KnowledgeProjectionWorker
from app.utils.utc import utc_now_db


class FakeNeo4jExecutor:
    def __init__(self, responses=None):
        self.calls: list[tuple[str, dict]] = []
        self.responses = list(responses or [])
        self.closed = False
        self.verified = False

    async def execute(self, query: str, parameters=None):
        self.calls.append((str(query), dict(parameters or {})))
        if self.responses:
            return self.responses.pop(0)
        return []

    async def verify_connectivity(self):
        self.verified = True

    async def close(self):
        self.closed = True


class FakeGraphitiClient:
    def __init__(self, *, search_edges=None, search_error: Exception | None = None):
        self.groups: list[str] = []
        self.episodes: list[dict] = []
        self.search_calls: list[dict] = []
        self.search_edges = list(search_edges or [])
        self.search_error = search_error
        self.built = 0
        self.closed = False
        self.driver = self

    async def health_check(self):
        return None

    async def execute_query(self, _query: str, **kwargs):
        group_id = dict(kwargs.get("params") or {}).get("group_id")
        if group_id is not None:
            self.groups.append(str(group_id))
        return SimpleNamespace(records=[])

    async def build_indices_and_constraints(self, delete_existing: bool = False):
        self.built += 1

    async def add_episode(self, **kwargs):
        self.episodes.append(dict(kwargs))

    async def search(self, query: str, *, group_ids=None, num_results=10, **kwargs):
        self.search_calls.append({
            "query": str(query),
            "group_ids": list(group_ids or []),
            "num_results": int(num_results),
        })
        if self.search_error is not None:
            raise self.search_error
        return list(self.search_edges)[: int(num_results)]

    async def close(self):
        self.closed = True


class GraphShadowStage6Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'stage6.db'}")
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        user = User(username=name, email=f"{name}@example.test", hashed_password="hash")
        db.add(user)
        await db.flush()
        return user

    async def _claim(self, db, *, user_id: int, record_id: int, statement: str, review_status: str = "confirmed"):
        source = KnowledgeSource(
            user_id=user_id,
            source_type="note",
            source_record_id=record_id,
            source_key=f"note:{record_id}",
            title_snapshot=f"Source {record_id}",
            status="active",
            current_revision=1,
        )
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=user_id,
            knowledge_source_id=int(source.id),
            revision=1,
            content_hash=hashlib.sha256(statement.encode()).hexdigest(),
            title_snapshot=source.title_snapshot,
            status="current",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=user_id,
            source_revision_id=int(revision.id),
            unit_type="note_body",
            ordinal=0,
            text=statement,
            text_hash=hashlib.sha256(statement.encode()).hexdigest(),
            locator={},
        )
        claim = Claim(
            user_id=user_id,
            source_revision_id=int(revision.id),
            statement=statement,
            fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(),
            confidence=0.9,
            derivation_type="manual",
            review_status=review_status,
            lifecycle_status="active",
        )
        db.add_all((unit, claim))
        await db.flush()
        db.add(ClaimEvidence(
            user_id=user_id,
            claim_id=int(claim.id),
            knowledge_unit_id=int(unit.id),
            excerpt=statement,
            char_start=0,
            char_end=len(statement),
            locator={},
            grounding_method="manual",
            confidence=0.9,
        ))
        await db.flush()
        return source, unit, claim

    async def test_stage6_legacy_flags_do_not_switch_graph_backend(self):
        async with self.sessions() as db:
            with (
                patch.object(settings, "GRAPH_BACKEND", "sql"),
                patch.object(settings, "NEO4J_GRAPH_ENABLED", True),
                patch.object(settings, "GRAPHITI_ENABLED", True),
            ):
                store = create_graph_store(db)
        self.assertIsInstance(store, SqlGraphStore)

    async def test_neo4j_rebuild_projects_only_current_user_confirmed_graph_without_raw_text(self):
        async with self.sessions() as db:
            owner = await self._user(db, "stage6-owner")
            stranger = await self._user(db, "stage6-stranger")
            _, _, visible = await self._claim(db, user_id=int(owner.id), record_id=1, statement="VISIBLE SECRET BODY")
            await self._claim(db, user_id=int(owner.id), record_id=2, statement="PENDING SECRET BODY", review_status="pending")
            await self._claim(db, user_id=int(stranger.id), record_id=3, statement="FOREIGN SECRET BODY")
            concept = Concept(
                user_id=int(owner.id),
                name="Feedback Loop",
                name_normalized="feedback loop",
                source="manual",
                review_status="confirmed",
            )
            db.add(concept)
            await db.flush()
            db.add(ClaimConceptLink(
                user_id=int(owner.id), claim_id=int(visible.id), concept_id=int(concept.id),
                relation_type="about", mention_text="feedback loop", confidence=1.0,
                derivation_type="manual", review_status="confirmed",
            ))
            await db.commit()

            executor = FakeNeo4jExecutor()
            result = await Neo4jGraphStore(db, executor=executor).rebuild_user(user_id=int(owner.id))

            self.assertEqual(result["claims"], 1)
            self.assertEqual(result["concepts"], 1)
            serialized_parameters = repr([params for _, params in executor.calls])
            self.assertNotIn("VISIBLE SECRET BODY", serialized_parameters)
            self.assertNotIn("PENDING SECRET BODY", serialized_parameters)
            self.assertNotIn("FOREIGN SECRET BODY", serialized_parameters)
            for query, params in executor.calls:
                if params.get("rows"):
                    for row in params["rows"]:
                        if "user_id" in row:
                            self.assertEqual(row["user_id"], int(owner.id))

    async def test_neo4j_fixed_path_query_is_user_scoped_and_returns_graph_hits(self):
        async with self.sessions() as db:
            owner = await self._user(db, "stage6-query-owner")
            executor = FakeNeo4jExecutor(responses=[[
                {"object_id": 22, "depth": 1, "confidence": 0.8, "relation_id": 7, "relation_type": "supports"}
            ]])
            store = Neo4jGraphStore(db, executor=executor)
            hits = await store.expand_claims(
                user_id=int(owner.id),
                claim_ids=(11,),
                patterns=("direct_claim_relations",),
                depth=2,
                limit=5,
            )
            self.assertEqual([(row.object_id, row.path_type) for row in hits], [(22, "direct_claim_relations")])
            query, params = executor.calls[0]
            self.assertIn("user_id:$user_id", query)
            self.assertEqual(params["user_id"], int(owner.id))
            self.assertEqual(params["frontier"], [11])
            self.assertEqual(params["visited"], [11])

    async def test_shadow_diff_reports_only_aggregate_mismatches(self):
        sql_hits = [GraphHit("claim", 1, "direct_claim_relations", 1, 0.9)]

        class FakeStore:
            def __init__(self, _db):
                pass

            async def expand_claims(self, **_kwargs):
                return [GraphHit("claim", 2, "direct_claim_relations", 1, 0.9)]

            async def close(self):
                return None

        async with self.sessions() as db:
            with patch("app.services.graph_shadow_service.Neo4jGraphStore", FakeStore):
                result = await compare_neo4j_claim_shadow(
                    db,
                    user_id=1,
                    claim_ids=(99,),
                    patterns=("direct_claim_relations",),
                    depth=1,
                    limit=5,
                    sql_hits=sql_hits,
                )
        self.assertEqual(result["status"], "compared")
        self.assertFalse(result["id_set_match"])
        self.assertEqual(result["missing_count"], 1)
        self.assertEqual(result["extra_count"], 1)
        self.assertNotIn("claim_ids", result)
        self.assertNotIn("sql_ids", result)
        self.assertNotIn("shadow_ids", result)

    @unittest.skipUnless(importlib.util.find_spec("graphiti_core"), "graphiti-core spike dependency is optional")
    async def test_graphiti_030_client_boundary_disables_raw_episode_storage(self):
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "stage6-placeholder-key", "GRAPHITI_TELEMETRY_ENABLED": "false"}),
            patch.object(settings, "NEO4J_URI", "bolt://127.0.0.1:17688"),
            patch.object(settings, "NEO4J_USER", "neo4j"),
            patch.object(settings, "NEO4J_PASSWORD", "stage6-placeholder-password"),
            patch.object(settings, "NEO4J_DATABASE", "neo4j"),
        ):
            client, episode_type = create_graphiti_client()
            try:
                self.assertFalse(client.store_raw_episode_content)
                self.assertEqual(str(episode_type.text.value), "text")
                self.assertEqual(client.driver.__class__.__name__, "Neo4jDriver")
                self.assertEqual(os.environ.get("GRAPHITI_TELEMETRY_ENABLED"), "false")
            finally:
                await client.close()

    async def test_graphiti_rebuild_uses_only_confirmed_visible_claims_and_user_group(self):
        async with self.sessions() as db:
            owner = await self._user(db, "graphiti-owner")
            stranger = await self._user(db, "graphiti-stranger")
            await self._claim(db, user_id=int(owner.id), record_id=10, statement="Confirmed claim")
            await self._claim(db, user_id=int(owner.id), record_id=11, statement="Pending claim", review_status="pending")
            await self._claim(db, user_id=int(stranger.id), record_id=12, statement="Foreign claim")
            await db.commit()

            client = FakeGraphitiClient()
            adapter = GraphitiShadowAdapter(
                db,
                client=client,
                episode_type=SimpleNamespace(text="text"),
            )
            result = await adapter.rebuild_user(user_id=int(owner.id))

            self.assertEqual(result["episodes"], 1)
            self.assertFalse(result["telemetry_enabled"])
            self.assertEqual(client.groups, [graphiti_group_id(int(owner.id))])
            self.assertEqual(len(client.episodes), 1)
            self.assertEqual(client.episodes[0]["episode_body"], "Confirmed claim")
            self.assertEqual(client.episodes[0]["group_id"], graphiti_group_id(int(owner.id)))
            self.assertNotIn("Pending claim", repr(client.episodes))
            self.assertNotIn("Foreign claim", repr(client.episodes))

    async def test_graphiti_temporal_history_includes_reviewed_boundaries_but_excludes_staged_and_foreign(self):
        async with self.sessions() as db:
            owner = await self._user(db, "graphiti-temporal-owner")
            stranger = await self._user(db, "graphiti-temporal-stranger")
            owner_memory = UserMemory(
                user_id=int(owner.id), memory_key="career_goal", memory_value="build agents",
                status="active", review_status="confirmed", category="goal",
            )
            foreign_memory = UserMemory(
                user_id=int(stranger.id), memory_key="career_goal", memory_value="private",
                status="active", review_status="confirmed", category="goal",
            )
            db.add_all((owner_memory, foreign_memory))
            await db.flush()
            now = utc_now_db()
            db.add_all((
                MemoryDeclaration(
                    user_id=int(owner.id), memory_id=int(owner_memory.id),
                    subject="user", predicate="career_goal", fact_key="goal:career",
                    value="learn RAG", valid_from=now - timedelta(days=20),
                    valid_to=now - timedelta(days=5), observed_at=now - timedelta(days=20),
                    confidence=1.0, review_status="superseded", source_type="manual", created_by="user",
                ),
                MemoryDeclaration(
                    user_id=int(owner.id), memory_id=int(owner_memory.id),
                    subject="user", predicate="career_goal", fact_key="goal:career",
                    value="build agent systems", valid_from=now - timedelta(days=5),
                    valid_to=None, observed_at=now - timedelta(days=5),
                    confidence=1.0, review_status="confirmed", source_type="manual", created_by="user",
                ),
                MemoryDeclaration(
                    user_id=int(owner.id), memory_id=int(owner_memory.id),
                    subject="user", predicate="career_goal", fact_key="goal:career",
                    value="unreviewed conflict", valid_from=now,
                    valid_to=None, observed_at=now,
                    confidence=0.6, review_status="staged", source_type="model", created_by="model",
                ),
                MemoryDeclaration(
                    user_id=int(stranger.id), memory_id=int(foreign_memory.id),
                    subject="other", predicate="career_goal", fact_key="goal:career",
                    value="foreign private fact", valid_from=now,
                    valid_to=None, observed_at=now,
                    confidence=1.0, review_status="confirmed", source_type="manual", created_by="user",
                ),
            ))
            await db.commit()

            client = FakeGraphitiClient()
            adapter = GraphitiShadowAdapter(
                db,
                client=client,
                episode_type=SimpleNamespace(text="text"),
            )
            result = await adapter.rebuild_user(user_id=int(owner.id))

            self.assertEqual(result["claim_episodes"], 0)
            self.assertEqual(result["temporal_episodes"], 2)
            self.assertFalse(result["raw_episode_storage"])
            bodies = "\n".join(str(row["episode_body"]) for row in client.episodes)
            self.assertIn("learn RAG", bodies)
            self.assertIn("build agent systems", bodies)
            self.assertIn("Review status: superseded", bodies)
            self.assertIn("Review status: confirmed", bodies)
            self.assertNotIn("unreviewed conflict", bodies)
            self.assertNotIn("foreign private fact", bodies)
            self.assertTrue(all(row["group_id"] == graphiti_group_id(int(owner.id)) for row in client.episodes))

    async def test_graphiti_rebuild_ignores_superseded_source_revision_claims(self):
        async with self.sessions() as db:
            owner = await self._user(db, "graphiti-revision-owner")
            source, _, old_claim = await self._claim(
                db,
                user_id=int(owner.id),
                record_id=20,
                statement="Old revision claim",
            )
            old_revision = await db.scalar(
                select(KnowledgeSourceRevision).where(
                    KnowledgeSourceRevision.id == int(old_claim.source_revision_id)
                )
            )
            old_revision.status = "superseded"
            source.current_revision = 2
            new_statement = "Current revision claim"
            new_revision = KnowledgeSourceRevision(
                user_id=int(owner.id),
                knowledge_source_id=int(source.id),
                revision=2,
                content_hash=hashlib.sha256(new_statement.encode()).hexdigest(),
                title_snapshot=source.title_snapshot,
                status="current",
            )
            db.add(new_revision)
            await db.flush()
            new_unit = KnowledgeUnit(
                user_id=int(owner.id),
                source_revision_id=int(new_revision.id),
                unit_type="note_body",
                ordinal=0,
                text=new_statement,
                text_hash=hashlib.sha256(new_statement.encode()).hexdigest(),
                locator={},
            )
            new_claim = Claim(
                user_id=int(owner.id),
                source_revision_id=int(new_revision.id),
                statement=new_statement,
                fingerprint=hashlib.sha256(new_statement.casefold().encode()).hexdigest(),
                confidence=0.9,
                derivation_type="manual",
                review_status="confirmed",
                lifecycle_status="active",
            )
            db.add_all((new_unit, new_claim))
            await db.flush()
            db.add(ClaimEvidence(
                user_id=int(owner.id),
                claim_id=int(new_claim.id),
                knowledge_unit_id=int(new_unit.id),
                excerpt=new_statement,
                char_start=0,
                char_end=len(new_statement),
                locator={},
                grounding_method="manual",
                confidence=0.9,
            ))
            await db.commit()

            client = FakeGraphitiClient()
            adapter = GraphitiShadowAdapter(
                db,
                client=client,
                episode_type=SimpleNamespace(text="text"),
            )
            result = await adapter.rebuild_user(user_id=int(owner.id))

            self.assertEqual(result["claim_episodes"], 1)
            bodies = [str(row["episode_body"]) for row in client.episodes]
            self.assertEqual(bodies, [new_statement])
            self.assertNotIn("Old revision claim", repr(client.episodes))

    async def test_graphiti_temporal_search_is_group_scoped_and_as_of_correct(self):
        async with self.sessions() as db:
            owner = await self._user(db, "graphiti-search-owner")
            memory = UserMemory(
                user_id=int(owner.id), memory_key="career_goal", memory_value="build agents",
                status="active", review_status="confirmed", category="goal",
            )
            db.add(memory)
            await db.flush()
            now = utc_now_db()
            old = MemoryDeclaration(
                user_id=int(owner.id), memory_id=int(memory.id),
                subject="user", predicate="career_goal", fact_key="goal:career",
                value="learn RAG", valid_from=now - timedelta(days=20),
                valid_to=now - timedelta(days=5), observed_at=now - timedelta(days=20),
                confidence=1.0, review_status="superseded", source_type="manual", created_by="user",
            )
            current = MemoryDeclaration(
                user_id=int(owner.id), memory_id=int(memory.id),
                subject="user", predicate="career_goal", fact_key="goal:career",
                value="build agent systems", valid_from=now - timedelta(days=5),
                valid_to=None, observed_at=now - timedelta(days=5),
                confidence=1.0, review_status="confirmed", source_type="manual", created_by="user",
            )
            db.add_all((old, current))
            await db.flush()
            owner_group = graphiti_group_id(int(owner.id))
            foreign_group = graphiti_group_id(int(owner.id) + 999)
            edges = [
                SimpleNamespace(
                    group_id=owner_group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(old.id)}"],
                    valid_at=(now - timedelta(days=20)).replace(tzinfo=timezone.utc),
                    invalid_at=(now - timedelta(days=5)).replace(tzinfo=timezone.utc),
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=owner_group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id)}-{int(current.id)}"],
                    valid_at=(now - timedelta(days=5)).replace(tzinfo=timezone.utc),
                    invalid_at=None,
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=foreign_group,
                    episodes=[f"mnemox-memory-declaration-{int(owner.id) + 999}-999"],
                    valid_at=(now - timedelta(days=1)).replace(tzinfo=timezone.utc),
                    invalid_at=None,
                    expired_at=None,
                ),
                SimpleNamespace(
                    group_id=owner_group,
                    episodes=["graphiti-unmapped-episode"],
                    valid_at=(now - timedelta(days=1)).replace(tzinfo=timezone.utc),
                    invalid_at=None,
                    expired_at=None,
                ),
            ]
            client = FakeGraphitiClient(search_edges=edges)
            adapter = GraphitiShadowAdapter(
                db,
                client=client,
                episode_type=SimpleNamespace(text="text"),
            )

            current_result = await adapter.search_temporal(
                user_id=int(owner.id),
                query="What is the career goal?",
                as_of=now.replace(tzinfo=timezone.utc),
                limit=10,
            )
            historical_result = await adapter.search_temporal(
                user_id=int(owner.id),
                query="What was the career goal?",
                as_of=(now - timedelta(days=10)).replace(tzinfo=timezone.utc),
                limit=10,
            )

            self.assertEqual(current_result.declaration_ids, (int(current.id),))
            self.assertEqual(historical_result.declaration_ids, (int(old.id),))
            self.assertEqual(client.search_calls[0]["group_ids"], [owner_group])
            self.assertEqual(client.search_calls[1]["group_ids"], [owner_group])
            self.assertGreaterEqual(current_result.filtered_edges, 2)
            self.assertEqual(current_result.unmapped_edges, 1)

            compared = await compare_graphiti_temporal_shadow(
                db,
                user_id=int(owner.id),
                fact_key="goal:career",
                query="PRIVATE QUERY MUST NOT APPEAR IN DIAGNOSTICS",
                as_of=now.replace(tzinfo=timezone.utc),
                limit=10,
                adapter=adapter,
            )
            self.assertEqual(compared["status"], "compared")
            self.assertEqual(compared["expected_recall"], 1.0)
            self.assertEqual(compared["stale_or_wrong_count"], 0)
            self.assertNotIn("query", compared)
            self.assertNotIn("PRIVATE QUERY", repr(compared))
            await db.commit()

    async def test_graphiti_search_failure_is_sanitized_and_does_not_poison_sql(self):
        async with self.sessions() as db:
            owner = await self._user(db, "graphiti-failure-owner")
            memory = UserMemory(
                user_id=int(owner.id), memory_key="goal", memory_value="safe",
                status="active", review_status="confirmed", category="goal",
            )
            db.add(memory)
            await db.flush()
            now = utc_now_db()
            db.add(MemoryDeclaration(
                user_id=int(owner.id), memory_id=int(memory.id), subject="user",
                predicate="goal", fact_key="goal:test", value="safe",
                valid_from=now - timedelta(days=1), valid_to=None, observed_at=now,
                confidence=1.0, review_status="confirmed", source_type="manual", created_by="user",
            ))
            await db.commit()

            client = FakeGraphitiClient(
                search_error=RuntimeError("provider failed while searching PRIVATE SECRET QUERY")
            )
            adapter = GraphitiShadowAdapter(
                db,
                client=client,
                episode_type=SimpleNamespace(text="text"),
            )
            result = await compare_graphiti_temporal_shadow(
                db,
                user_id=int(owner.id),
                fact_key="goal:test",
                query="PRIVATE SECRET QUERY",
                as_of=now.replace(tzinfo=timezone.utc),
                adapter=adapter,
            )

            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["error_type"], "RuntimeError")
            self.assertNotIn("PRIVATE SECRET QUERY", repr(result))
            self.assertEqual(await db.scalar(text("SELECT 1")), 1)

    async def test_neo4j_projection_lag_summary_quantifies_backlog_without_payloads(self):
        with (
            patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "reference"),
            patch.object(settings, "NEO4J_GRAPH_SHADOW", True),
        ):
            async with self.sessions() as db:
                owner = await self._user(db, "neo4j-lag-owner")
                await enqueue_user_knowledge_rebuild(db, user_id=int(owner.id), force=True)
                graph_row = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.user_id == int(owner.id),
                        KnowledgeProjectionOutbox.projection_target == NEO4J_GRAPH_PROJECTION_TARGET,
                    )
                )
                graph_row.created_at = utc_now_db() - timedelta(seconds=42)
                await db.commit()
                user_id = int(owner.id)

            async with self.sessions() as db:
                pending = await neo4j_projection_lag_summary(db, user_id=user_id)
                self.assertEqual(pending["status_counts"].get("pending"), 1)
                self.assertGreaterEqual(pending["oldest_pending_age_seconds"], 41.0)
                self.assertNotIn("payload", repr(pending))
                row = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.user_id == user_id,
                        KnowledgeProjectionOutbox.projection_target == NEO4J_GRAPH_PROJECTION_TARGET,
                    )
                )
                row.status = "processed"
                row.processed_at = utc_now_db()
                await db.commit()

            async with self.sessions() as db:
                processed = await neo4j_projection_lag_summary(db, user_id=user_id)
                self.assertEqual(processed["status_counts"].get("processed"), 1)
                self.assertEqual(processed["oldest_pending_age_seconds"], 0.0)
                self.assertGreaterEqual(processed["latest_processed_lag_seconds"], 41.0)

    async def test_stage7_runtime_selector_enables_neo4j_projection_without_legacy_flags(self):
        with (
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", False),
            patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "reference"),
            patch.object(settings, "GRAPH_BACKEND", "neo4j"),
            patch.object(settings, "NEO4J_GRAPH_SHADOW", False),
            patch.object(settings, "NEO4J_GRAPH_ENABLED", False),
        ):
            async with self.sessions() as db:
                owner = await self._user(db, "neo4j-runtime-projection-owner")
                await enqueue_user_knowledge_rebuild(db, user_id=int(owner.id), force=True)
                await db.commit()
                user_id = int(owner.id)

            async with self.sessions() as db:
                graph_row = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.user_id == user_id,
                        KnowledgeProjectionOutbox.projection_target == NEO4J_GRAPH_PROJECTION_TARGET,
                    )
                )
            self.assertIsNotNone(graph_row)

            worker = KnowledgeProjectionWorker(
                self.sessions,
                worker_id="stage7-neo4j-runtime-worker",
                batch_size=1,
                poll_interval_seconds=0.01,
            )
            self.assertEqual(worker._projection_targets, (NEO4J_GRAPH_PROJECTION_TARGET,))

    async def test_neo4j_shadow_outbox_is_target_isolated_and_worker_leaves_chroma_pending(self):
        processed_users: list[int] = []

        class FakeProjectionStore:
            def __init__(self, _db):
                pass

            async def rebuild_user(self, *, user_id: int):
                processed_users.append(int(user_id))
                return {"backend": "neo4j", "rebuilt": True}

            async def close(self):
                return None

        with (
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", False),
            patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "reference"),
            patch.object(settings, "NEO4J_GRAPH_SHADOW", True),
            patch.object(settings, "NEO4J_GRAPH_ENABLED", False),
        ):
            async with self.sessions() as db:
                owner = await self._user(db, "neo4j-outbox-owner")
                await enqueue_user_knowledge_rebuild(db, user_id=int(owner.id), force=True)
                await db.commit()
                user_id = int(owner.id)

            async with self.sessions() as db:
                rows = list(
                    (
                        await db.scalars(
                            select(KnowledgeProjectionOutbox).where(
                                KnowledgeProjectionOutbox.user_id == user_id
                            )
                        )
                    ).all()
                )
            self.assertEqual(
                {str(row.projection_target) for row in rows},
                {"chroma_knowledge", NEO4J_GRAPH_PROJECTION_TARGET},
            )

            worker = KnowledgeProjectionWorker(
                self.sessions,
                worker_id="stage6-neo4j-shadow-worker",
                batch_size=10,
                poll_interval_seconds=0.01,
            )
            self.assertEqual(worker._projection_targets, (NEO4J_GRAPH_PROJECTION_TARGET,))
            with patch(
                "app.services.graph_store.neo4j_store.Neo4jGraphStore",
                FakeProjectionStore,
            ):
                result = await worker.run_once()

            self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
            self.assertEqual(processed_users, [user_id])
            async with self.sessions() as db:
                graph_row = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.user_id == user_id,
                        KnowledgeProjectionOutbox.projection_target == NEO4J_GRAPH_PROJECTION_TARGET,
                    )
                )
                chroma_row = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.user_id == user_id,
                        KnowledgeProjectionOutbox.projection_target == "chroma_knowledge",
                    )
                )
            self.assertEqual(graph_row.status, "processed")
            self.assertEqual(chroma_row.status, "pending")

    async def test_neo4j_shadow_projection_failure_uses_existing_retry_state(self):
        class BrokenProjectionStore:
            def __init__(self, _db):
                pass

            async def rebuild_user(self, *, user_id: int):
                raise RuntimeError(f"synthetic graph failure for {int(user_id)}")

            async def close(self):
                return None

        with (
            patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "reference"),
            patch.object(settings, "NEO4J_GRAPH_SHADOW", True),
        ):
            async with self.sessions() as db:
                owner = await self._user(db, "neo4j-retry-owner")
                await enqueue_user_knowledge_rebuild(db, user_id=int(owner.id), force=True)
                await db.commit()
                user_id = int(owner.id)

            async with self.sessions() as db:
                row = await claim_next_knowledge_projection(
                    db,
                    worker_id="stage6-failure-worker",
                    max_attempts=2,
                    lease_seconds=120,
                    projection_targets=(NEO4J_GRAPH_PROJECTION_TARGET,),
                )
                self.assertIsNotNone(row)
                outbox_id = int(row.id)
                await db.commit()

            with patch(
                "app.services.graph_store.neo4j_store.Neo4jGraphStore",
                BrokenProjectionStore,
            ):
                async with self.sessions() as db:
                    status = await process_claimed_knowledge_projection(
                        db,
                        outbox_id=outbox_id,
                        worker_id="stage6-failure-worker",
                        max_attempts=2,
                        retry_base_seconds=0,
                    )
                    await db.commit()

            self.assertEqual(status, "failed")
            async with self.sessions() as db:
                stored = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.id == outbox_id
                    )
                )
            self.assertEqual(stored.status, "failed")
            self.assertEqual(stored.attempts, 1)
            self.assertIsNone(stored.dead_lettered_at)
            self.assertIn("RuntimeError", str(stored.last_error))

            async with self.sessions() as db:
                row = await claim_next_knowledge_projection(
                    db,
                    worker_id="stage6-failure-worker",
                    max_attempts=2,
                    lease_seconds=120,
                    projection_targets=(NEO4J_GRAPH_PROJECTION_TARGET,),
                )
                self.assertIsNotNone(row)
                self.assertEqual(int(row.attempts), 2)
                await db.commit()

            with patch(
                "app.services.graph_store.neo4j_store.Neo4jGraphStore",
                BrokenProjectionStore,
            ):
                async with self.sessions() as db:
                    status = await process_claimed_knowledge_projection(
                        db,
                        outbox_id=outbox_id,
                        worker_id="stage6-failure-worker",
                        max_attempts=2,
                        retry_base_seconds=0,
                    )
                    await db.commit()

            self.assertEqual(status, "failed")
            async with self.sessions() as db:
                stored = await db.scalar(
                    select(KnowledgeProjectionOutbox).where(
                        KnowledgeProjectionOutbox.id == outbox_id
                    )
                )
            self.assertEqual(stored.attempts, 2)
            self.assertIsNotNone(stored.dead_lettered_at)


if __name__ == "__main__":
    unittest.main()
