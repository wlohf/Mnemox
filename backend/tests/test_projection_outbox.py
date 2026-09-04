"""Projection outbox durability, idempotency, replay and isolation tests."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept
from app.models.learner_model import LearnerEvidence, ProjectionOutbox, UserConceptState
from app.models.learning_event import LearningEvent
from app.models.user import User
from app.services.learning_event_service import record_learning_event
from app.services.projection_outbox_service import (
    POSTGRES_OUTBOX_RETRY_POLICY_LOCK_KEY,
    POSTGRES_PROJECTION_LOCK_NAMESPACE,
    _lock_outbox_retry_policy,
    _lock_projection_users,
    enqueue_for_learning_event,
    process_event_projection,
    process_outbox,
    replay_projections,
)


class ProjectionOutboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "outbox.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime.now().replace(microsecond=0) - timedelta(hours=1)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _owner_and_concept(self, name: str) -> tuple[int, int]:
        async with self.sessions() as session:
            user = User(username=name, email=f"{name}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            concept = Concept(user_id=user.id, name=name, name_normalized=name, mastery=0, source="test")
            session.add(concept)
            await session.flush()
            result = (int(user.id), int(concept.id))
            await session.commit()
            return result

    async def test_learning_event_and_outbox_are_committed_and_rolled_back_together(self):
        user_id, _ = await self._owner_and_concept("atomic")
        async with self.sessions() as session:
            await record_learning_event(session, user_id, "practice.answer", source="test", payload={"score": 0.8})
            await session.rollback()
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(LearningEvent)), 0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(ProjectionOutbox)), 0)

    async def test_duplicate_enqueue_and_consumption_are_idempotent(self):
        user_id, concept_id = await self._owner_and_concept("dedupe")
        async with self.sessions() as session:
            event_item = await record_learning_event(
                session, user_id, "practice.answer", source="test",
                payload={"score": 0.8}, occurred_at=self.now,
            )
            first = await enqueue_for_learning_event(session, event_item, concept_id=concept_id)
            second = await enqueue_for_learning_event(session, event_item, concept_id=concept_id)
            self.assertEqual(first["id"], second["id"])
            result = await process_outbox(session, user_id=user_id)
            await session.commit()
            self.assertGreaterEqual(result["processed"], 1)
        async with self.sessions() as session:
            before = await session.scalar(select(func.count()).select_from(LearnerEvidence))
            await replay_projections(session, user_id, concept_id=concept_id)
            await session.commit()
        async with self.sessions() as session:
            after = await session.scalar(select(func.count()).select_from(LearnerEvidence))
            self.assertEqual(before, after)

    async def test_event_payload_concept_is_projected_without_direct_state_write(self):
        user_id, concept_id = await self._owner_and_concept("event-driven")
        async with self.sessions() as session:
            await record_learning_event(
                session,
                user_id,
                "practice.answer",
                source="test",
                payload={"concept_id": concept_id, "score": 0.65},
                occurred_at=self.now,
            )
            result = await process_outbox(session, user_id=user_id)
            await session.commit()
            self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
        async with self.sessions() as session:
            evidence = await session.scalar(
                select(LearnerEvidence).where(
                    LearnerEvidence.user_id == user_id,
                    LearnerEvidence.concept_id == concept_id,
                )
            )
            self.assertIsNotNone(evidence)
            self.assertAlmostEqual(evidence.score, 0.65)

    async def test_event_scoped_processing_does_not_consume_other_pending_rows(self):
        owner_id, owner_concept = await self._owner_and_concept("event-scope-owner")
        other_id, other_concept = await self._owner_and_concept("event-scope-other")
        async with self.sessions() as session:
            owner_event = await record_learning_event(
                session,
                owner_id,
                "practice.answer",
                source="test",
                payload={"concept_id": owner_concept, "score": 0.8},
                occurred_at=self.now,
            )
            await record_learning_event(
                session,
                other_id,
                "practice.answer",
                source="test",
                payload={"concept_id": other_concept, "score": 0.4},
                occurred_at=self.now,
            )

            result = await process_event_projection(
                session,
                user_id=owner_id,
                source_event_id=int(owner_event["id"]),
            )
            await session.commit()

        self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
        async with self.sessions() as session:
            owner_row = await session.scalar(
                select(ProjectionOutbox).where(ProjectionOutbox.user_id == owner_id)
            )
            other_row = await session.scalar(
                select(ProjectionOutbox).where(ProjectionOutbox.user_id == other_id)
            )
            self.assertEqual(owner_row.status, "processed")
            self.assertEqual(other_row.status, "pending")

    async def test_batch_processing_uses_bounded_explicit_flushes(self):
        user_id, concept_id = await self._owner_and_concept("batched-flushes")
        async with self.sessions() as session:
            for index in range(3):
                await record_learning_event(
                    session,
                    user_id,
                    "note.created",
                    source="test",
                    payload={"concept_id": concept_id, "index": index},
                    occurred_at=self.now + timedelta(seconds=index),
                )
            await session.flush()

            flush_calls = 0
            original_flush = session.flush
            savepoint_calls = 0
            original_begin_nested = session.begin_nested

            async def counted_flush(*args, **kwargs):
                nonlocal flush_calls
                flush_calls += 1
                return await original_flush(*args, **kwargs)

            def counted_begin_nested(*args, **kwargs):
                nonlocal savepoint_calls
                savepoint_calls += 1
                return original_begin_nested(*args, **kwargs)

            session.flush = counted_flush  # type: ignore[method-assign]
            session.begin_nested = counted_begin_nested  # type: ignore[method-assign]
            result = await process_outbox(session, user_id=user_id, limit=3)

            self.assertEqual(result, {"claimed": 3, "processed": 3, "failed": 0})
            self.assertLessEqual(flush_calls, 4)
            self.assertEqual(savepoint_calls, 0)

    async def test_postgresql_projection_batch_locks_users_in_stable_order(self):
        class CapturingSession:
            def __init__(self, dialect_name: str) -> None:
                self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
                self.calls: list[tuple[str, dict[str, int]]] = []

            async def execute(self, statement, parameters):
                self.calls.append((str(statement), dict(parameters)))

        postgres_session = CapturingSession("postgresql")
        await _lock_projection_users(postgres_session, [9, 3, 9])

        self.assertEqual(
            [params for _, params in postgres_session.calls],
            [
                {"namespace": POSTGRES_PROJECTION_LOCK_NAMESPACE, "user_id": 3},
                {"namespace": POSTGRES_PROJECTION_LOCK_NAMESPACE, "user_id": 9},
            ],
        )
        self.assertTrue(
            all("pg_advisory_xact_lock" in statement for statement, _ in postgres_session.calls)
        )

        sqlite_session = CapturingSession("sqlite")
        await _lock_projection_users(sqlite_session, [3])
        self.assertEqual(sqlite_session.calls, [])

    async def test_global_projection_claim_does_not_preselect_candidate_ids(self):
        first_user_id, first_concept_id = await self._owner_and_concept("global-claim-first")
        second_user_id, second_concept_id = await self._owner_and_concept("global-claim-second")
        async with self.sessions() as session:
            await record_learning_event(
                session,
                first_user_id,
                "practice.answer",
                source="test",
                payload={"concept_id": first_concept_id, "score": 0.8},
                occurred_at=self.now,
            )
            await record_learning_event(
                session,
                second_user_id,
                "practice.answer",
                source="test",
                payload={"concept_id": second_concept_id, "score": 0.6},
                occurred_at=self.now,
            )
            await session.commit()

        async with self.sessions() as session:
            outbox_claim_queries: list[str] = []
            original_execute = session.execute

            async def recording_execute(statement, *args, **kwargs):
                statement_text = str(statement)
                if (
                    statement_text.lstrip().upper().startswith("SELECT")
                    and "FROM projection_outbox" in statement_text
                ):
                    outbox_claim_queries.append(statement_text)
                return await original_execute(statement, *args, **kwargs)

            session.execute = recording_execute  # type: ignore[method-assign]
            result = await process_outbox(
                session,
                limit=1,
                now=self.now,
                resolve_retry_policy=False,
                reconcile_terminal_state=False,
            )

            await session.rollback()

        self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
        self.assertEqual(len(outbox_claim_queries), 1)

    async def test_postgresql_retry_policy_uses_shared_and_exclusive_transaction_locks(self):
        class CapturingSession:
            def __init__(self, dialect_name: str) -> None:
                self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
                self.calls: list[tuple[str, dict[str, int]]] = []

            async def execute(self, statement, parameters):
                self.calls.append((str(statement), dict(parameters)))

        postgres_session = CapturingSession("postgresql")
        await _lock_outbox_retry_policy(postgres_session, exclusive=False)
        await _lock_outbox_retry_policy(postgres_session, exclusive=True)

        self.assertEqual(
            [params for _, params in postgres_session.calls],
            [
                {"key": POSTGRES_OUTBOX_RETRY_POLICY_LOCK_KEY},
                {"key": POSTGRES_OUTBOX_RETRY_POLICY_LOCK_KEY},
            ],
        )
        self.assertIn("pg_advisory_xact_lock_shared", postgres_session.calls[0][0])
        self.assertIn("pg_advisory_xact_lock", postgres_session.calls[1][0])
        self.assertNotIn("pg_advisory_xact_lock_shared", postgres_session.calls[1][0])

        sqlite_session = CapturingSession("sqlite")
        await _lock_outbox_retry_policy(sqlite_session, exclusive=False)
        self.assertEqual(sqlite_session.calls, [])

    async def test_stale_processing_row_is_recovered_and_user_filter_isolated(self):
        owner_id, owner_concept = await self._owner_and_concept("recover-owner")
        other_id, other_concept = await self._owner_and_concept("recover-other")
        async with self.sessions() as session:
            owner_event = await record_learning_event(session, owner_id, "practice.recall", source="test", payload={"score": 1.0}, occurred_at=self.now)
            other_event = await record_learning_event(session, other_id, "practice.recall", source="test", payload={"score": 0.0}, occurred_at=self.now)
            owner_row = await enqueue_for_learning_event(session, owner_event, concept_id=owner_concept)
            await enqueue_for_learning_event(session, other_event, concept_id=other_concept)
            row = await session.get(ProjectionOutbox, owner_row["id"])
            row.status = "processing"
            row.locked_at = self.now - timedelta(minutes=10)
            await session.commit()
        async with self.sessions() as session:
            result = await process_outbox(session, user_id=owner_id, now=self.now)
            await session.commit()
            self.assertGreaterEqual(result["processed"], 1)
        async with self.sessions() as session:
            owner_count = await session.scalar(select(func.count()).select_from(LearnerEvidence).where(LearnerEvidence.user_id == owner_id))
            other_count = await session.scalar(select(func.count()).select_from(LearnerEvidence).where(LearnerEvidence.user_id == other_id))
            self.assertEqual(owner_count, 1)
            self.assertEqual(other_count, 0)

    async def test_concept_and_event_delete_cascade_outbox_rows(self):
        user_id, concept_id = await self._owner_and_concept("cascade")
        async with self.sessions() as session:
            event_item = await record_learning_event(session, user_id, "practice.answer", source="test", payload={"score": 1.0})
            await enqueue_for_learning_event(session, event_item, concept_id=concept_id)
            await session.commit()
        async with self.sessions() as session:
            concept = await session.get(Concept, concept_id)
            await session.delete(concept)
            await session.commit()
        async with self.sessions() as session:
            rows = await session.scalar(select(func.count()).select_from(ProjectionOutbox).where(ProjectionOutbox.concept_id == concept_id))
            self.assertEqual(rows, 0)

    async def test_replay_processes_more_than_one_worker_batch(self):
        user_id, concept_id = await self._owner_and_concept("paged-replay")
        async with self.sessions() as session:
            session.add_all(
                [
                    LearningEvent(
                        user_id=user_id,
                        event_type="note.created",
                        event_category="study",
                        source="test",
                        event_data={"concept_id": concept_id},
                        timestamp=self.now + timedelta(seconds=index),
                    )
                    for index in range(525)
                ]
            )
            await session.commit()

        async with self.sessions() as session:
            result = await replay_projections(session, user_id, concept_id=concept_id)
            await session.commit()
            self.assertEqual(result["events"], 525)
            self.assertEqual(result["queued"], 525)
            self.assertEqual(result["processed"], 525)

        async with self.sessions() as session:
            pending_count = await session.scalar(
                select(func.count()).select_from(ProjectionOutbox).where(
                    ProjectionOutbox.user_id == user_id,
                    ProjectionOutbox.status != "processed",
                )
            )
            self.assertEqual(pending_count, 0)

    async def test_failed_projection_stops_after_max_attempts(self):
        user_id, concept_id = await self._owner_and_concept("retry-cap")
        async with self.sessions() as session:
            event_item = await record_learning_event(
                session,
                user_id,
                "practice.answer",
                source="test",
                payload={"concept_id": concept_id, "score": "not-a-number api_key=outbox-secret"},
                occurred_at=self.now,
            )
            row = await session.scalar(
                select(ProjectionOutbox).where(
                    ProjectionOutbox.source_event_id == int(event_item["id"]),
                    ProjectionOutbox.concept_id == concept_id,
                )
            )
            self.assertIsNotNone(row)
            await session.commit()

        for attempt in range(3):
            async with self.sessions() as session:
                result = await process_outbox(
                    session,
                    user_id=user_id,
                    max_attempts=3,
                    now=self.now + timedelta(minutes=attempt + 1),
                )
                await session.commit()
                self.assertEqual(result["failed"], 1)

        async with self.sessions() as session:
            result = await process_outbox(
                session,
                user_id=user_id,
                max_attempts=3,
                now=self.now + timedelta(days=1),
            )
            row = await session.scalar(
                select(ProjectionOutbox).where(ProjectionOutbox.user_id == user_id)
            )
            self.assertEqual(result, {"claimed": 0, "processed": 0, "failed": 0})
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.attempts, 3)
            self.assertIn("could not convert string to float", row.last_error)
            self.assertIn("[REDACTED]", row.last_error)
            self.assertNotIn("outbox-secret", row.last_error)

    async def test_review_event_updates_state_only_after_outbox_consumption(self):
        user_id, concept_id = await self._owner_and_concept("review-outbox")
        async with self.sessions() as session:
            await record_learning_event(
                session,
                user_id,
                "review.completed",
                source="test",
                payload={
                    "concept_id": concept_id,
                    "target_type": "wrong_question",
                    "target_id": 42,
                    "quality": 4,
                    "normalized_score": 0.9,
                },
                occurred_at=self.now,
            )
            self.assertIsNone(
                await session.scalar(
                    select(UserConceptState).where(
                        UserConceptState.user_id == user_id,
                        UserConceptState.concept_id == concept_id,
                    )
                )
            )
            result = await process_outbox(session, user_id=user_id)
            await session.commit()
            self.assertEqual(result["processed"], 1)

        async with self.sessions() as session:
            evidence = await session.scalar(
                select(LearnerEvidence).where(
                    LearnerEvidence.user_id == user_id,
                    LearnerEvidence.concept_id == concept_id,
                    LearnerEvidence.evidence_type == "review_result",
                )
            )
            self.assertIsNotNone(evidence)
            self.assertAlmostEqual(evidence.score, 0.9)


if __name__ == "__main__":
    unittest.main()
