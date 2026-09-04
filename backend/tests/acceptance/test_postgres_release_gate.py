"""PostgreSQL 16 release-gate acceptance tests.

These tests are intentionally skipped during the normal SQLite unit suite.
CI supplies ``POSTGRES_ACCEPTANCE_DATABASE_URL`` after migrating a fresh
PostgreSQL 16 service through the production migration entrypoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.concept import Concept, ConceptAlias
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    EntityResolutionCandidate,
    KnowledgeProjectionOutbox,
    KnowledgeExtractionRun,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.material import Material
from app.models.learner_model import (
    LearnerEvidence,
    ProjectionOutbox,
    ProjectionOutboxWorkerHeartbeat,
)
from app.models.agent import AgentJob
from app.models.question import ReviewSchedule
from app.models.user import User
from app.services.agent_runtime_worker import AgentRuntimeWorker
from app.services.coach_preference_service import update_coach_preferences
from app.services.learning_event_service import record_learning_event
from app.services.knowledge_source_service import (
    create_manual_claim,
    delete_source,
    list_visible_claims,
    register_material_source,
)
from app.services.knowledge_extraction_service import claim_next_extraction_run
from app.services.knowledge_extraction_worker import KnowledgeExtractionWorker
from app.schemas.knowledge_extraction import ExtractedConceptMention
from app.services.entity_resolution_service import resolve_claim_mentions
from app.services.knowledge_projection_service import (
    claim_next_knowledge_projection,
    enqueue_knowledge_object_projection,
)
from app.services.projection_outbox_service import (
    get_outbox_retry_policy_state,
    process_outbox,
    resolve_outbox_retry_policy,
)
from app.services.projection_outbox_worker import ProjectionOutboxWorker
from app.utils.operation_lock import (
    serialized_global_operation,
    serialized_user_operation,
    stable_advisory_lock_key,
)


DATABASE_URL = os.environ.get("POSTGRES_ACCEPTANCE_DATABASE_URL", "").strip()
POSTGRES_URL_CONFIGURED = DATABASE_URL.startswith("postgresql+asyncpg://")


def _expected_alembic_head() -> str:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic revision graph has no head")
    return revision


EXPECTED_ALEMBIC_HEAD = _expected_alembic_head()


@unittest.skipUnless(
    POSTGRES_URL_CONFIGURED,
    "set POSTGRES_ACCEPTANCE_DATABASE_URL to run the PostgreSQL release gate",
)
class PostgresReleaseGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.run_token = uuid.uuid4().hex[:12]

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_projection_events(self, count: int, *, label: str) -> list[int]:
        event_ids: list[int] = []
        async with self.sessions() as session:
            for index in range(count):
                suffix = f"{self.run_token}-{label}-{index}"
                user = User(
                    username=f"pg-{suffix}"[:50],
                    email=f"pg-{suffix}@example.com"[:200],
                    hashed_password="acceptance-only",
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                concept = Concept(
                    user_id=int(user.id),
                    name=f"PostgreSQL acceptance {suffix}"[:120],
                    name_normalized=f"postgresql-acceptance-{suffix}"[:120],
                    mastery=0,
                    source="acceptance",
                )
                session.add(concept)
                await session.flush()
                event = await record_learning_event(
                    session,
                    int(user.id),
                    "practice.answer",
                    source="postgres-acceptance",
                    payload={
                        "concept_id": int(concept.id),
                        "score": 0.55 + (index % 4) * 0.1,
                    },
                    dedupe_key=f"pg-release-gate:{suffix}",
                    occurred_at=datetime.now(),
                )
                event_ids.append(int(event["id"]))
            await session.commit()
        return event_ids

    async def _drain_projection_outbox(self) -> None:
        """Clear work intentionally left pending by earlier acceptance cases."""

        while True:
            async with self.sessions() as session:
                result = await process_outbox(session, limit=500)
                if result["claimed"]:
                    await session.commit()
                else:
                    await session.rollback()
            if not result["claimed"]:
                return

    async def test_database_is_postgresql_16_at_expected_alembic_head(self) -> None:
        async with self.sessions() as session:
            server_version = int(await session.scalar(text("SHOW server_version_num")))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            user_columns = set(
                (
                    await session.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = 'users'"
                        )
                    )
                ).scalars()
            )

        self.assertGreaterEqual(server_version, 160000)
        self.assertLess(server_version, 170000)
        self.assertEqual(revision, EXPECTED_ALEMBIC_HEAD)
        self.assertTrue(
            {
                "token_version",
                "failed_login_count",
                "login_failed_window_started_at",
                "login_locked_until",
            }.issubset(user_columns)
        )

    async def test_canonical_claim_schema_lifecycle_and_user_isolation(self) -> None:
        async with self.sessions() as session:
            owner = User(
                username=f"pg-claim-owner-{self.run_token}"[:50],
                email=f"pg-claim-owner-{self.run_token}@example.test"[:200],
                hashed_password="acceptance-only",
                is_active=True,
            )
            outsider = User(
                username=f"pg-claim-outsider-{self.run_token}"[:50],
                email=f"pg-claim-outsider-{self.run_token}@example.test"[:200],
                hashed_password="acceptance-only",
                is_active=True,
            )
            session.add_all([owner, outsider])
            await session.flush()
            material = Material(
                user_id=int(owner.id),
                title="PostgreSQL Claim Stage 1",
                content="PostgreSQL preserves grounded Claim evidence.",
                content_hash=hashlib.sha256(
                    b"PostgreSQL preserves grounded Claim evidence."
                ).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
            session.add(material)
            await session.flush()
            first = await register_material_source(
                session,
                user_id=int(owner.id),
                material_id=int(material.id),
            )
            with self.assertRaises(PermissionError):
                await register_material_source(
                    session,
                    user_id=int(outsider.id),
                    material_id=int(material.id),
                )
            unit = await session.scalar(
                select(KnowledgeUnit).where(
                    KnowledgeUnit.source_revision_id == int(first.id)
                )
            )
            claim = await create_manual_claim(
                session,
                user_id=int(owner.id),
                source_revision_id=int(first.id),
                knowledge_unit_id=int(unit.id),
                statement="PostgreSQL keeps a grounded Claim.",
                excerpt="PostgreSQL preserves grounded Claim evidence.",
            )
            await session.commit()

            material.content = "A new PostgreSQL source revision."
            material.content_hash = hashlib.sha256(material.content.encode()).hexdigest()
            second = await register_material_source(
                session,
                user_id=int(owner.id),
                material_id=int(material.id),
            )
            await session.commit()
            await session.refresh(claim)
            revision_statuses = list(
                (
                    await session.scalars(
                        select(KnowledgeSourceRevision.status)
                        .where(
                            KnowledgeSourceRevision.knowledge_source_id
                            == int(first.knowledge_source_id)
                        )
                        .order_by(KnowledgeSourceRevision.revision)
                    )
                ).all()
            )

            self.assertEqual(second.revision, 2)
            self.assertEqual(revision_statuses, ["superseded", "current"])
            self.assertEqual(claim.lifecycle_status, "superseded")
            self.assertEqual(await list_visible_claims(session, user_id=int(owner.id)), [])

            self.assertTrue(
                await delete_source(
                    session,
                    user_id=int(owner.id),
                    source_type="material",
                    source_record_id=int(material.id),
                )
            )
            await session.commit()
            remaining_active = await session.scalar(
                select(func.count())
                .select_from(Claim)
                .where(
                    Claim.user_id == int(owner.id),
                    Claim.lifecycle_status == "active",
                )
            )
            self.assertEqual(remaining_active, 0)

    async def test_knowledge_extraction_run_uses_skip_locked_and_persists_grounded_pending_claim(self) -> None:
        async with self.sessions() as session:
            user = User(
                username=f"pg-extraction-{self.run_token}"[:50],
                email=f"pg-extraction-{self.run_token}@example.test"[:200],
                hashed_password="acceptance-only",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            material = Material(
                user_id=int(user.id),
                title="PostgreSQL Stage 2 extraction",
                content="Grounding：Evidence must resolve to the source Unit.",
                content_hash=hashlib.sha256(
                    b"Grounding: Evidence must resolve to the source Unit."
                ).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
            session.add(material)
            await session.flush()
            revision = await register_material_source(
                session,
                user_id=int(user.id),
                material_id=int(material.id),
            )
            await session.commit()
            user_id = int(user.id)
            revision_id = int(revision.id)

        async with self.sessions() as first, self.sessions() as second:
            leased = await claim_next_extraction_run(first, worker_id="pg-lock-holder")
            self.assertIsNotNone(leased)
            skipped = await claim_next_extraction_run(second, worker_id="pg-lock-contender")
            self.assertIsNone(skipped)
            await second.rollback()
            await first.rollback()

        worker = KnowledgeExtractionWorker(
            self.sessions,
            worker_id="pg-stage2-worker",
            batch_size=1,
        )
        result = await worker.run_once()
        async with self.sessions() as session:
            run = await session.scalar(
                select(KnowledgeExtractionRun).where(
                    KnowledgeExtractionRun.source_revision_id == revision_id
                )
            )
            claim = await session.scalar(
                select(Claim).where(
                    Claim.user_id == user_id,
                    Claim.source_revision_id == revision_id,
                )
            )
            evidence_count = await session.scalar(
                select(func.count()).select_from(ClaimEvidence).where(
                    ClaimEvidence.claim_id == int(claim.id)
                )
            )

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(claim.review_status, "pending")
        self.assertEqual(evidence_count, 1)

    async def test_stage3_exact_semantic_review_and_projection_queue_use_postgres_constraints(self) -> None:
        async with self.sessions() as session:
            owner = User(
                username=f"pg-stage3-owner-{self.run_token}"[:50],
                email=f"pg-stage3-owner-{self.run_token}@example.test"[:200],
                hashed_password="acceptance-only",
                is_active=True,
            )
            outsider = User(
                username=f"pg-stage3-other-{self.run_token}"[:50],
                email=f"pg-stage3-other-{self.run_token}@example.test"[:200],
                hashed_password="acceptance-only",
                is_active=True,
            )
            session.add_all((owner, outsider))
            await session.flush()
            canonical = Concept(
                user_id=int(owner.id),
                name="PostgreSQL entity resolution",
                name_normalized="postgresql entity resolution",
                source="acceptance",
                review_status="confirmed",
            )
            outsider_concept = Concept(
                user_id=int(outsider.id),
                name="Cross-user sentinel",
                name_normalized="cross-user sentinel",
                source="acceptance",
                review_status="confirmed",
            )
            session.add_all((canonical, outsider_concept))
            await session.flush()
            session.add(
                ConceptAlias(
                    user_id=int(owner.id),
                    concept_id=int(canonical.id),
                    alias="pg resolver",
                    alias_normalized="pg resolver",
                    source="acceptance",
                )
            )
            material = Material(
                user_id=int(owner.id),
                title="PostgreSQL Stage 3 resolution",
                content="Every semantic candidate remains reviewable.",
                content_hash=hashlib.sha256(
                    b"Every semantic candidate remains reviewable."
                ).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
            session.add(material)
            await session.flush()
            revision = await register_material_source(
                session,
                user_id=int(owner.id),
                material_id=int(material.id),
            )
            unit = await session.scalar(
                select(KnowledgeUnit).where(
                    KnowledgeUnit.source_revision_id == int(revision.id)
                )
            )
            run = await session.scalar(
                select(KnowledgeExtractionRun).where(
                    KnowledgeExtractionRun.source_revision_id == int(revision.id),
                    KnowledgeExtractionRun.extractor_type == "deterministic",
                )
            )
            claim = await create_manual_claim(
                session,
                user_id=int(owner.id),
                source_revision_id=int(revision.id),
                knowledge_unit_id=int(unit.id),
                statement="Semantic candidates require review.",
                excerpt="Every semantic candidate remains reviewable.",
            )
            await enqueue_knowledge_object_projection(
                session,
                user_id=int(owner.id),
                object_type="concept",
                object_id=int(canonical.id),
            )

            class AcceptanceIndex:
                async def query_concepts(self, *, user_id: int, text: str, top_k: int):
                    self_user = int(user_id)
                    if self_user != int(owner.id):
                        raise AssertionError("wrong user scope")
                    return [
                        {"concept_id": int(outsider_concept.id), "score": 0.99},
                        {"concept_id": int(canonical.id), "score": 0.91},
                    ][:top_k]

            with patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", True):
                exact_stats = await resolve_claim_mentions(
                    session,
                    run=run,
                    unit=unit,
                    claim=claim,
                    mentions=(ExtractedConceptMention(text="pg resolver"),),
                )
                semantic_stats = await resolve_claim_mentions(
                    session,
                    run=run,
                    unit=unit,
                    claim=claim,
                    mentions=(ExtractedConceptMention(text="implicit database mapping"),),
                    embedding_index=AcceptanceIndex(),
                )
            await session.commit()
            owner_id = int(owner.id)

        async with self.sessions() as session:
            links = list(
                (
                    await session.scalars(
                        select(ClaimConceptLink).where(ClaimConceptLink.user_id == owner_id)
                    )
                ).all()
            )
            candidates = list(
                (
                    await session.scalars(
                        select(EntityResolutionCandidate).where(
                            EntityResolutionCandidate.user_id == owner_id
                        )
                    )
                ).all()
            )
            queue = list(
                (
                    await session.scalars(
                        select(KnowledgeProjectionOutbox).where(
                            KnowledgeProjectionOutbox.user_id == owner_id,
                            KnowledgeProjectionOutbox.status == "pending",
                        )
                    )
                ).all()
            )

        self.assertEqual(exact_stats["alias"], 1)
        self.assertEqual(semantic_stats["pending"], 1)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].review_status, "confirmed")
        self.assertEqual(
            {row.candidate_concept_id for row in candidates},
            {canonical.id},
        )
        self.assertEqual(
            {row.decision for row in candidates},
            {"accepted", "pending"},
        )
        self.assertGreaterEqual(len(queue), 3)
        self.assertTrue(all(set(row.payload) <= {"object_type"} for row in queue))

        locked_id = int(queue[0].id)
        async with self.sessions() as locker:
            locked = await locker.scalar(
                select(KnowledgeProjectionOutbox)
                .where(KnowledgeProjectionOutbox.id == locked_id)
                .with_for_update()
            )
            self.assertIsNotNone(locked)
            async with self.sessions() as contender:
                claimed = await claim_next_knowledge_projection(
                    contender,
                    worker_id=f"pg-stage3-contender-{self.run_token}",
                    max_attempts=5,
                    lease_seconds=120,
                )
                self.assertIsNotNone(claimed)
                self.assertNotEqual(int(claimed.id), locked_id)
                await contender.rollback()
            await locker.rollback()

    async def test_long_operation_advisory_lock_is_held_and_released(self) -> None:
        namespace = f"acceptance-operation-{self.run_token}"
        user_id = 42
        lock_key = stable_advisory_lock_key(namespace, user_id)

        async with self.sessions() as session:
            async with serialized_user_operation(
                session,
                namespace=namespace,
                user_id=user_id,
            ):
                async with self.engine.connect() as observer:
                    acquired_while_held = bool(
                        await observer.scalar(
                            text("SELECT pg_try_advisory_lock(:lock_key)"),
                            {"lock_key": lock_key},
                        )
                    )

        self.assertFalse(acquired_while_held)
        async with self.engine.connect() as observer:
            acquired_after_release = bool(
                await observer.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
            self.assertTrue(acquired_after_release)
            self.assertTrue(
                bool(
                    await observer.scalar(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                )
            )

    async def test_global_operation_shared_and_exclusive_locks_are_mutually_exclusive(self) -> None:
        namespace = f"acceptance-global-operation-{self.run_token}"
        lock_key = stable_advisory_lock_key(namespace, "global")

        async with self.sessions() as session:
            async with serialized_global_operation(
                session,
                namespace=namespace,
                exclusive=False,
            ):
                async with self.engine.connect() as observer:
                    exclusive_while_shared = bool(
                        await observer.scalar(
                            text("SELECT pg_try_advisory_lock(:lock_key)"),
                            {"lock_key": lock_key},
                        )
                    )

        async with self.sessions() as session:
            async with serialized_global_operation(
                session,
                namespace=namespace,
                exclusive=True,
            ):
                async with self.engine.connect() as observer:
                    shared_while_exclusive = bool(
                        await observer.scalar(
                            text("SELECT pg_try_advisory_lock_shared(:lock_key)"),
                            {"lock_key": lock_key},
                        )
                    )

        self.assertFalse(exclusive_while_shared)
        self.assertFalse(shared_while_exclusive)
        async with self.engine.connect() as observer:
            acquired_after_release = bool(
                await observer.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
            self.assertTrue(acquired_after_release)
            self.assertTrue(
                bool(
                    await observer.scalar(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                )
            )

    async def test_global_consumer_skips_a_locked_row_and_keeps_working(self) -> None:
        locked_event_id, available_event_id = await self._seed_projection_events(
            2,
            label="skip-locked",
        )

        async with self.sessions() as locker:
            locked_row = await locker.scalar(
                select(ProjectionOutbox)
                .where(ProjectionOutbox.source_event_id == locked_event_id)
                .with_for_update()
            )
            self.assertIsNotNone(locked_row)

            async with self.sessions() as consumer:
                result = await process_outbox(consumer, limit=1)
                await consumer.commit()

            self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
            async with self.sessions() as observer:
                statuses = dict(
                    (
                        await observer.execute(
                            select(ProjectionOutbox.source_event_id, ProjectionOutbox.status)
                            .where(
                                ProjectionOutbox.source_event_id.in_(
                                    [locked_event_id, available_event_id]
                                )
                            )
                        )
                    ).all()
                )
            self.assertEqual(statuses[locked_event_id], "pending")
            self.assertEqual(statuses[available_event_id], "processed")
            await locker.rollback()

        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id=f"acceptance-skip-locked-{self.run_token}",
            batch_size=1,
            poll_interval_seconds=0.05,
        )
        self.assertEqual(
            await worker.run_once(),
            {"claimed": 1, "processed": 1, "failed": 0},
        )

    async def test_retry_policy_upgrade_is_serialized_and_shared(self) -> None:
        async with self.sessions() as session:
            initial_max_attempts = await resolve_outbox_retry_policy(
                session,
                max_attempts=5,
                retry_policy_version=1,
            )
            await session.commit()
        self.assertEqual(initial_max_attempts, 5)

        async def upgrade_policy() -> int:
            async with self.sessions() as session:
                max_attempts = await resolve_outbox_retry_policy(
                    session,
                    max_attempts=7,
                    retry_policy_version=2,
                )
                await session.commit()
                return max_attempts

        upgraded_values = await asyncio.gather(upgrade_policy(), upgrade_policy())
        self.assertEqual(upgraded_values, [7, 7])

        async with self.sessions() as session:
            self.assertEqual(await get_outbox_retry_policy_state(session), (7, 2))
            with self.assertRaises(ValueError):
                await resolve_outbox_retry_policy(
                    session,
                    max_attempts=8,
                    retry_policy_version=2,
                )
            await session.rollback()

    async def test_two_workers_process_exactly_once_and_persist_heartbeats(self) -> None:
        # The SKIP LOCKED case deliberately leaves its locked row pending after
        # rollback.  Drain shared queue state so this case measures only the 12
        # rows it seeds, regardless of unittest method order.
        await self._drain_projection_outbox()
        event_ids = await self._seed_projection_events(12, label="dual-worker")
        worker_ids = [
            f"acceptance-worker-a-{self.run_token}",
            f"acceptance-worker-b-{self.run_token}",
        ]
        workers = [
            ProjectionOutboxWorker(
                self.sessions,
                worker_id=worker_id,
                batch_size=6,
                poll_interval_seconds=0.05,
                heartbeat_enabled=True,
                heartbeat_interval_seconds=0.05,
                heartbeat_ttl_seconds=6,
            )
            for worker_id in worker_ids
        ]

        results = await asyncio.gather(*(worker.run_once() for worker in workers))
        self.assertTrue(all(result["claimed"] > 0 for result in results))
        self.assertEqual(sum(result["claimed"] for result in results), len(event_ids))
        self.assertEqual(sum(result["processed"] for result in results), len(event_ids))
        self.assertEqual(sum(result["failed"] for result in results), 0)

        async with self.sessions() as session:
            outbox_rows = (
                await session.scalars(
                    select(ProjectionOutbox).where(
                        ProjectionOutbox.source_event_id.in_(event_ids)
                    )
                )
            ).all()
            evidence_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(LearnerEvidence)
                    .where(LearnerEvidence.source_event_id.in_(event_ids))
                )
                or 0
            )
            distinct_evidence_events = int(
                await session.scalar(
                    select(func.count(func.distinct(LearnerEvidence.source_event_id))).where(
                        LearnerEvidence.source_event_id.in_(event_ids)
                    )
                )
                or 0
            )

        self.assertEqual(len(outbox_rows), len(event_ids))
        self.assertTrue(all(row.status == "processed" for row in outbox_rows))
        self.assertTrue(all(row.attempts == 1 for row in outbox_rows))
        self.assertEqual(evidence_count, len(event_ids))
        self.assertEqual(distinct_evidence_events, len(event_ids))

        drained = await asyncio.gather(*(worker.run_once() for worker in workers))
        self.assertTrue(all(result["claimed"] == 0 for result in drained))

        for worker in workers:
            worker.start()
        try:
            for _ in range(100):
                async with self.sessions() as session:
                    heartbeat_count = int(
                        await session.scalar(
                            select(func.count())
                            .select_from(ProjectionOutboxWorkerHeartbeat)
                            .where(
                                ProjectionOutboxWorkerHeartbeat.worker_id.in_(worker_ids),
                                ProjectionOutboxWorkerHeartbeat.stopped_at.is_(None),
                            )
                        )
                        or 0
                    )
                if heartbeat_count == 2:
                    break
                await asyncio.sleep(0.02)
            else:
                self.fail("both PostgreSQL worker heartbeats were not persisted")
        finally:
            await asyncio.gather(*(worker.stop() for worker in workers))

        async with self.sessions() as session:
            heartbeat_rows = (
                await session.scalars(
                    select(ProjectionOutboxWorkerHeartbeat).where(
                        ProjectionOutboxWorkerHeartbeat.worker_id.in_(worker_ids)
                    )
                )
            ).all()

        self.assertEqual({row.worker_id for row in heartbeat_rows}, set(worker_ids))
        self.assertTrue(all(row.last_heartbeat_at is not None for row in heartbeat_rows))
        self.assertTrue(all(row.stopped_at is not None for row in heartbeat_rows))

    async def test_two_agent_runtime_workers_do_not_duplicate_one_due_user(self) -> None:
        now = datetime(2026, 9, 1, 12, 0, 0)
        suffix = f"{self.run_token}-agent-runtime"
        async with self.sessions() as session:
            user = User(
                username=f"pg-{suffix}"[:50],
                email=f"pg-{suffix}@example.com"[:200],
                hashed_password="acceptance-only",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await update_coach_preferences(
                session,
                user_id,
                {
                    "proactive_enabled": True,
                    "allowed_channels": ["agent_panel"],
                    "time_zone": "UTC",
                },
            )
            session.add_all(
                [
                    ReviewSchedule(
                        user_id=user_id,
                        item_type="chapter",
                        item_id=index,
                        scheduled_date=now,
                        status="pending",
                        is_archived=False,
                    )
                    for index in range(1, 7)
                ]
            )
            await session.commit()

        workers = [
            AgentRuntimeWorker(
                self.sessions,
                poll_interval_seconds=30,
                batch_size=10,
                user_timeout_seconds=10,
            )
            for _ in range(2)
        ]
        results = await asyncio.gather(*(worker.run_once(now=now) for worker in workers))

        self.assertEqual(sum(result["scanned"] for result in results), 1)
        self.assertEqual(sum(result["nudges_created"] for result in results), 1)
        self.assertEqual(sum(result["failed"] for result in results), 0)
        async with self.sessions() as session:
            jobs = (
                await session.scalars(
                    select(AgentJob).where(
                        AgentJob.user_id == user_id,
                        AgentJob.scenario == "review_debt_rescue_v1",
                    )
                )
            ).all()
        self.assertEqual(len(jobs), 1)
