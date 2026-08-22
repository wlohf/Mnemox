"""PostgreSQL 16 release-gate acceptance tests.

These tests are intentionally skipped during the normal SQLite unit suite.
CI supplies ``POSTGRES_ACCEPTANCE_DATABASE_URL`` after migrating a fresh
PostgreSQL 16 service through the production migration entrypoint.
"""
from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.concept import Concept
from app.models.learner_model import (
    LearnerEvidence,
    ProjectionOutbox,
    ProjectionOutboxWorkerHeartbeat,
)
from app.models.user import User
from app.services.learning_event_service import record_learning_event
from app.services.projection_outbox_service import (
    get_outbox_retry_policy_state,
    process_outbox,
    resolve_outbox_retry_policy,
)
from app.services.projection_outbox_worker import ProjectionOutboxWorker


DATABASE_URL = os.environ.get("POSTGRES_ACCEPTANCE_DATABASE_URL", "").strip()
EXPECTED_ALEMBIC_HEAD = "20260822_10"
POSTGRES_URL_CONFIGURED = DATABASE_URL.startswith("postgresql+asyncpg://")


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

    async def test_database_is_postgresql_16_at_expected_alembic_head(self) -> None:
        async with self.sessions() as session:
            server_version = int(await session.scalar(text("SHOW server_version_num")))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))

        self.assertGreaterEqual(server_version, 160000)
        self.assertLess(server_version, 170000)
        self.assertEqual(revision, EXPECTED_ALEMBIC_HEAD)

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
