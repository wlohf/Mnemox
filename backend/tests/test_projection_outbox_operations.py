"""Operational queue, alerting, and recovery tests for projection outbox."""
from __future__ import annotations

import importlib
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.config import settings
from app.models import learner_model as learner_model_models
from app.models.concept import Concept
from app.models.learner_model import ProjectionOutbox
from app.models.user import User
from app.routers import learner_model as learner_model_router
from app.services import projection_outbox_service
from app.services.learning_event_service import record_learning_event


class ProjectionOutboxOperationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "outbox-operations.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime.now().replace(microsecond=0)
        self.owner, self.owner_concept = await self._create_user_and_concept("ops-owner")
        self.other, self.other_concept = await self._create_user_and_concept("ops-other")

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user_and_concept(self, name: str) -> tuple[User, int]:
        async with self.sessions() as session:
            user = User(
                username=name,
                email=f"{name}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            concept = Concept(
                user_id=int(user.id),
                name=name,
                name_normalized=name,
                mastery=0,
                source="test",
            )
            session.add(concept)
            await session.flush()
            detached = User(
                id=int(user.id),
                username=name,
                email=user.email,
                hashed_password="hash",
                is_active=True,
            )
            await session.commit()
            return detached, int(concept.id)

    async def _create_outbox_row(
        self,
        user: User,
        concept_id: int,
        suffix: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> int:
        async with self.sessions() as session:
            event_payload: dict[str, object] = {
                "concept_id": concept_id,
                "score": 0.75,
                "suffix": suffix,
            }
            if payload:
                event_payload.update(payload)
            item = await record_learning_event(
                session,
                int(user.id),
                "practice.answer",
                source="test",
                payload=event_payload,
                occurred_at=self.now,
            )
            row = await session.scalar(
                select(ProjectionOutbox).where(
                    ProjectionOutbox.source_event_id == int(item["id"]),
                    ProjectionOutbox.user_id == int(user.id),
                )
            )
            self.assertIsNotNone(row)
            await session.commit()
            return int(row.id)

    async def _mark_failed(
        self,
        row_id: int,
        *,
        attempts: int,
        last_error: str = "projection failed",
        available_at: datetime | None = None,
        dead_lettered: bool | None = None,
    ) -> None:
        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, row_id)
            self.assertIsNotNone(row)
            row.status = "failed"
            row.attempts = attempts
            row.last_error = last_error
            row.dead_lettered_at = (
                self.now
                if (attempts >= 5 if dead_lettered is None else dead_lettered)
                else None
            )
            row.available_at = available_at or self.now
            await session.commit()

    async def test_dead_letter_queue_is_user_scoped_and_retry_resets_terminal_row(self):
        owner_row = await self._create_outbox_row(self.owner, self.owner_concept, "owner-dead-letter")
        other_row = await self._create_outbox_row(self.other, self.other_concept, "other-dead-letter")
        await self._mark_failed(owner_row, attempts=5, last_error="owner failure")
        await self._mark_failed(other_row, attempts=5, last_error="other failure")

        list_dead_letter_tasks = getattr(projection_outbox_service, "list_dead_letter_tasks", None)
        retry_dead_letter_task = getattr(projection_outbox_service, "retry_dead_letter_task", None)
        self.assertIsNotNone(list_dead_letter_tasks)
        self.assertIsNotNone(retry_dead_letter_task)

        async with self.sessions() as session:
            queue = await list_dead_letter_tasks(
                session,
                int(self.owner.id),
                max_attempts=5,
            )
            self.assertEqual(queue["total"], 1)
            self.assertEqual([item["id"] for item in queue["items"]], [owner_row])
            self.assertNotIn("last_error", queue["items"][0])
            self.assertNotIn("payload", queue["items"][0])
            self.assertEqual(
                queue["items"][0]["error_code"],
                "projection_outbox.processing_failed",
            )
            self.assertRegex(queue["items"][0]["error_fingerprint"], r"^[0-9a-f]{16}$")

            retried = await retry_dead_letter_task(
                session,
                int(self.owner.id),
                owner_row,
                max_attempts=5,
                now=self.now,
            )
            self.assertEqual(retried["status"], "pending")
            self.assertEqual(retried["attempts"], 0)
            self.assertNotIn("last_error", retried)
            await session.commit()

        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, owner_row)
            self.assertEqual(row.status, "pending")
            self.assertEqual(row.attempts, 0)
            self.assertIsNone(row.last_error)

    async def test_max_attempt_failure_becomes_dead_letter_and_is_not_claimed_again(self):
        outbox_id = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "terminal-failure",
            payload={"score": "not-a-number"},
        )
        dead_lettered_at = getattr(ProjectionOutbox, "dead_lettered_at", None)
        self.assertIsNotNone(dead_lettered_at)

        async with self.sessions() as session:
            first = await projection_outbox_service.process_outbox(
                session,
                max_attempts=2,
                now=self.now,
            )
            self.assertEqual(first, {"claimed": 1, "processed": 0, "failed": 1})
            second = await projection_outbox_service.process_outbox(
                session,
                max_attempts=2,
                now=self.now + timedelta(seconds=3),
            )
            self.assertEqual(second, {"claimed": 1, "processed": 0, "failed": 1})
            await session.commit()

        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.attempts, 2)
            self.assertIsNotNone(row.dead_lettered_at)
            result = await projection_outbox_service.process_outbox(
                session,
                max_attempts=2,
                now=self.now + timedelta(days=1),
            )
            self.assertEqual(result, {"claimed": 0, "processed": 0, "failed": 0})

    async def test_runtime_reconciles_legacy_terminal_failures_at_configured_caps(self):
        cap_three = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "legacy-cap-three",
        )
        cap_ten = await self._create_outbox_row(
            self.other,
            self.other_concept,
            "legacy-cap-ten",
        )
        retryable = await self._create_outbox_row(
            self.other,
            self.other_concept,
            "legacy-retryable",
        )
        await self._mark_failed(cap_three, attempts=3, dead_lettered=False)
        await self._mark_failed(cap_ten, attempts=10, dead_lettered=False)
        await self._mark_failed(retryable, attempts=9, dead_lettered=False)

        async with self.sessions() as session:
            result = await projection_outbox_service.process_outbox(
                session,
                user_id=int(self.owner.id),
                max_attempts=3,
                now=self.now,
            )
            self.assertEqual(result, {"claimed": 0, "processed": 0, "failed": 0})
            await session.commit()

        still_retryable = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "legacy-five-at-cap-ten",
        )
        await self._mark_failed(still_retryable, attempts=5, dead_lettered=False)
        async with self.sessions() as session:
            result = await projection_outbox_service.process_outbox(
                session,
                user_id=int(self.owner.id),
                max_attempts=10,
                retry_policy_version=2,
                now=self.now,
            )
            self.assertEqual(result, {"claimed": 2, "processed": 2, "failed": 0})
            await session.commit()

        async with self.sessions() as session:
            queue = await projection_outbox_service.list_dead_letter_tasks(
                session,
                int(self.other.id),
                max_attempts=10,
                retry_policy_version=2,
            )
            self.assertEqual([item["id"] for item in queue["items"]], [cap_ten])
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                max_attempts=10,
                retry_policy_version=2,
                now=self.now,
            )
            self.assertEqual(snapshot["metrics"]["dead_letter"], 1)
            await session.commit()

        async with self.sessions() as session:
            cap_three_row = await session.get(ProjectionOutbox, cap_three)
            cap_ten_row = await session.get(ProjectionOutbox, cap_ten)
            retryable_row = await session.get(ProjectionOutbox, retryable)
            still_retryable_row = await session.get(ProjectionOutbox, still_retryable)
            self.assertEqual(cap_three_row.status, "processed")
            self.assertIsNone(cap_three_row.dead_lettered_at)
            self.assertIsNotNone(cap_ten_row.dead_lettered_at)
            self.assertIsNone(retryable_row.dead_lettered_at)
            self.assertEqual(still_retryable_row.status, "processed")
            self.assertIsNone(still_retryable_row.dead_lettered_at)

    async def test_versioned_retry_policy_unifies_mixed_caps_and_reopens_legacy_dead_letter(self):
        outbox_id = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "versioned-mixed-cap-terminal-state",
        )
        await self._mark_failed(outbox_id, attempts=5, dead_lettered=False)

        async with self.sessions() as session:
            reconciled = await projection_outbox_service.reconcile_outbox_terminal_failures(
                session,
                user_id=int(self.owner.id),
                max_attempts=3,
                retry_policy_version=1,
                now=self.now,
            )
            self.assertEqual(reconciled, 1)
            marked_row = await session.get(ProjectionOutbox, outbox_id)
            self.assertIsNotNone(marked_row.dead_lettered_at)
            await session.commit()

        async with self.sessions() as session:
            reconciled = await projection_outbox_service.reconcile_outbox_terminal_failures(
                session,
                user_id=int(self.owner.id),
                max_attempts=10,
                retry_policy_version=2,
                now=self.now + timedelta(seconds=1),
            )
            self.assertEqual(reconciled, 1)
            reopened_row = await session.get(ProjectionOutbox, outbox_id)
            self.assertIsNone(reopened_row.dead_lettered_at)
            await session.commit()

        async with self.sessions() as session:
            reconciled = await projection_outbox_service.reconcile_outbox_terminal_failures(
                session,
                user_id=int(self.owner.id),
                max_attempts=3,
                retry_policy_version=1,
                now=self.now + timedelta(seconds=2),
            )
            self.assertEqual(reconciled, 0)
            result = await projection_outbox_service.process_outbox(
                session,
                user_id=int(self.owner.id),
                max_attempts=3,
                retry_policy_version=1,
                now=self.now + timedelta(seconds=2),
            )
            self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
            await session.commit()

        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertEqual(row.status, "processed")
            self.assertIsNone(row.dead_lettered_at)
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                max_attempts=3,
                retry_policy_version=1,
                now=self.now + timedelta(seconds=3),
            )
            self.assertEqual(snapshot["retry_policy_version"], 2)
            self.assertEqual(snapshot["metrics"]["retry_policy_max_attempts"], 10)
            rendered = projection_outbox_service.render_outbox_prometheus_metrics(snapshot)
            self.assertIn("mnemox_projection_outbox_retry_policy_max_attempts 10", rendered)
            self.assertIn("mnemox_projection_outbox_retry_policy_version 2", rendered)

    async def test_retry_policy_rejects_conflicting_cap_for_the_same_version(self):
        outbox_id = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "retry-policy-version-conflict",
        )
        await self._mark_failed(outbox_id, attempts=3, dead_lettered=False)

        async with self.sessions() as session:
            await projection_outbox_service.reconcile_outbox_terminal_failures(
                session,
                user_id=int(self.owner.id),
                max_attempts=3,
                retry_policy_version=1,
                now=self.now,
            )
            await session.commit()

        async with self.sessions() as session:
            with self.assertRaisesRegex(ValueError, "retry policy version"):
                await projection_outbox_service.reconcile_outbox_terminal_failures(
                    session,
                    user_id=int(self.owner.id),
                    max_attempts=10,
                    retry_policy_version=1,
                    now=self.now + timedelta(seconds=1),
                )

    async def test_durable_snapshot_aggregates_terminal_retryable_and_stale_rows(self):
        dead_letter = await self._create_outbox_row(self.owner, self.owner_concept, "dead-letter")
        retryable = await self._create_outbox_row(self.owner, self.owner_concept, "retryable")
        stale = await self._create_outbox_row(self.other, self.other_concept, "stale")
        pending = await self._create_outbox_row(self.other, self.other_concept, "pending")
        await self._mark_failed(dead_letter, attempts=5)
        await self._mark_failed(retryable, attempts=2)

        async with self.sessions() as session:
            stale_row = await session.get(ProjectionOutbox, stale)
            stale_row.status = "processing"
            stale_row.attempts = 1
            stale_row.locked_at = self.now - timedelta(minutes=6)
            pending_row = await session.get(ProjectionOutbox, pending)
            pending_row.created_at = self.now - timedelta(minutes=20)
            pending_row.available_at = self.now - timedelta(minutes=20)
            await session.commit()

        get_outbox_operations_snapshot = getattr(
            projection_outbox_service,
            "get_outbox_operations_snapshot",
            None,
        )
        self.assertIsNotNone(get_outbox_operations_snapshot)

        async with self.sessions() as session:
            snapshot = await get_outbox_operations_snapshot(
                session,
                max_attempts=5,
                now=self.now,
                backlog_count_threshold=1,
                backlog_age_seconds=60,
                worker_expected=True,
            )

        self.assertEqual(snapshot["status"], "critical")
        self.assertEqual(snapshot["metrics"]["dead_letter"], 1)
        self.assertEqual(snapshot["metrics"]["retryable"], 1)
        self.assertEqual(snapshot["metrics"]["stale_processing"], 1)
        self.assertEqual(snapshot["metrics"]["ready"], 2)
        self.assertGreaterEqual(snapshot["metrics"]["oldest_ready_age_seconds"], 20 * 60)
        self.assertEqual(
            {alert["code"] for alert in snapshot["alerts"]},
            {
                "projection_outbox_dead_letter",
                "projection_outbox_stale_processing",
                "projection_outbox_backlog_age",
                "projection_outbox_no_active_worker",
            },
        )

    async def test_durable_snapshot_excludes_processed_history_from_queue_total(self):
        processed = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "processed-history",
        )
        pending = await self._create_outbox_row(
            self.other,
            self.other_concept,
            "active-pending",
        )

        async with self.sessions() as session:
            processed_row = await session.get(ProjectionOutbox, processed)
            self.assertIsNotNone(processed_row)
            processed_row.status = "processed"
            processed_row.processed_at = self.now
            await session.commit()

        async with self.sessions() as session:
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                now=self.now,
            )

        self.assertEqual(snapshot["metrics"]["total"], 1)
        self.assertEqual(snapshot["metrics"]["pending"], 1)
        self.assertEqual(snapshot["metrics"]["ready"], 1)

    async def test_durable_snapshot_distinguishes_active_and_stale_workers(self):
        heartbeat_model = getattr(
            learner_model_models,
            "ProjectionOutboxWorkerHeartbeat",
            None,
        )
        record_outbox_worker_heartbeat = getattr(
            projection_outbox_service,
            "record_outbox_worker_heartbeat",
            None,
        )
        self.assertIsNotNone(heartbeat_model)
        self.assertIsNotNone(record_outbox_worker_heartbeat)

        async with self.sessions() as session:
            await record_outbox_worker_heartbeat(
                session,
                worker_id="active-worker",
                started_at=self.now - timedelta(minutes=1),
                last_heartbeat_at=self.now,
            )
            await record_outbox_worker_heartbeat(
                session,
                worker_id="stale-worker",
                started_at=self.now - timedelta(minutes=3),
                last_heartbeat_at=self.now - timedelta(minutes=2),
            )
            await session.commit()

        async with self.sessions() as session:
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                now=self.now,
                heartbeat_ttl_seconds=30,
            )

        self.assertEqual(snapshot["metrics"]["known_workers"], 2)
        self.assertEqual(snapshot["metrics"]["active_workers"], 1)
        self.assertEqual(snapshot["metrics"]["stale_workers"], 1)

    async def test_durable_snapshot_alerts_when_active_worker_poll_is_failing(self):
        record_outbox_worker_heartbeat = getattr(
            projection_outbox_service,
            "record_outbox_worker_heartbeat",
            None,
        )
        self.assertIsNotNone(record_outbox_worker_heartbeat)

        async with self.sessions() as session:
            await record_outbox_worker_heartbeat(
                session,
                worker_id="poll-error-worker",
                started_at=self.now - timedelta(minutes=5),
                last_heartbeat_at=self.now,
                last_poll_at=self.now - timedelta(minutes=1),
                last_success_at=self.now - timedelta(minutes=2),
                last_error_at=self.now - timedelta(minutes=1),
            )
            await record_outbox_worker_heartbeat(
                session,
                worker_id="recovered-worker",
                started_at=self.now - timedelta(minutes=5),
                last_heartbeat_at=self.now,
                last_poll_at=self.now - timedelta(seconds=10),
                last_success_at=self.now - timedelta(seconds=10),
                last_error_at=self.now - timedelta(minutes=2),
            )
            await record_outbox_worker_heartbeat(
                session,
                worker_id="projection-failure-worker",
                started_at=self.now - timedelta(minutes=5),
                last_heartbeat_at=self.now,
                last_poll_at=self.now - timedelta(seconds=5),
                last_success_at=self.now - timedelta(seconds=5),
                last_error_at=self.now - timedelta(seconds=5),
                last_projection_failure_at=self.now - timedelta(seconds=5),
            )
            await session.commit()

        async with self.sessions() as session:
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                now=self.now,
                heartbeat_ttl_seconds=30,
            )

        self.assertEqual(snapshot["metrics"]["active_workers"], 3)
        self.assertEqual(snapshot["metrics"]["error_workers"], 1)
        self.assertEqual(snapshot["status"], "critical")
        self.assertIn(
            "projection_outbox_worker_poll_error",
            {alert["code"] for alert in snapshot["alerts"]},
        )
        rendered = projection_outbox_service.render_outbox_prometheus_metrics(snapshot)
        self.assertIn("mnemox_projection_outbox_error_workers 1", rendered)
        self.assertIn(
            'mnemox_projection_outbox_alert{code="projection_outbox_worker_poll_error"} 1',
            rendered,
        )

    async def test_read_only_snapshot_uses_the_canonical_policy_without_reconciling(self):
        outbox_id = await self._create_outbox_row(
            self.owner,
            self.owner_concept,
            "read-only-metrics-policy",
        )
        await self._mark_failed(outbox_id, attempts=3, dead_lettered=True)

        async with self.sessions() as session:
            effective_max_attempts = await projection_outbox_service.resolve_outbox_retry_policy(
                session,
                max_attempts=10,
                retry_policy_version=2,
                now=self.now,
            )
            self.assertEqual(effective_max_attempts, 10)
            await session.commit()

        async with self.sessions() as session:
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                max_attempts=3,
                retry_policy_version=1,
                now=self.now + timedelta(seconds=1),
                resolve_retry_policy=False,
                reconcile_terminal_state=False,
            )
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertIsNotNone(row)
            self.assertIsNotNone(row.dead_lettered_at)

        self.assertEqual(snapshot["metrics"]["retry_policy_max_attempts"], 10)
        self.assertEqual(snapshot["retry_policy_version"], 2)
        self.assertEqual(snapshot["metrics"]["dead_letter"], 0)
        self.assertEqual(snapshot["metrics"]["retryable"], 1)

    async def test_read_only_snapshot_alerts_on_same_version_retry_policy_conflict(self):
        async with self.sessions() as session:
            effective_max_attempts = await projection_outbox_service.resolve_outbox_retry_policy(
                session,
                max_attempts=5,
                retry_policy_version=1,
                now=self.now,
            )
            self.assertEqual(effective_max_attempts, 5)
            await session.commit()

        async with self.sessions() as session:
            snapshot = await projection_outbox_service.get_outbox_operations_snapshot(
                session,
                max_attempts=3,
                retry_policy_version=1,
                now=self.now + timedelta(seconds=1),
                resolve_retry_policy=False,
                reconcile_terminal_state=False,
            )

        self.assertEqual(snapshot["status"], "critical")
        self.assertEqual(snapshot["metrics"]["retry_policy_config_conflict"], 1)
        self.assertIn(
            "projection_outbox_retry_policy_config_conflict",
            {alert["code"] for alert in snapshot["alerts"]},
        )
        rendered = projection_outbox_service.render_outbox_prometheus_metrics(snapshot)
        self.assertIn("mnemox_projection_outbox_retry_policy_config_conflict 1", rendered)
        self.assertIn(
            'mnemox_projection_outbox_alert{code="projection_outbox_retry_policy_config_conflict"} 1',
            rendered,
        )

    async def test_internal_metrics_requires_token_and_exposes_only_aggregate_data(self):
        outbox_id = await self._create_outbox_row(self.owner, self.owner_concept, "metrics")
        await self._mark_failed(outbox_id, attempts=5, last_error="owner failure should stay private")

        spec = importlib.util.find_spec("app.routers.outbox_operations")
        self.assertIsNotNone(spec)
        operations_router = importlib.import_module("app.routers.outbox_operations")
        metrics_endpoint = getattr(operations_router, "projection_outbox_metrics", None)
        self.assertIsNotNone(metrics_endpoint)
        policy_model = getattr(
            learner_model_models,
            "ProjectionOutboxRetryPolicy",
            None,
        )
        self.assertIsNotNone(policy_model)

        async with self.sessions() as session:
            with patch.object(settings, "OUTBOX_OPS_TOKEN", "monitor-token", create=True):
                with self.assertRaises(HTTPException) as context:
                    await metrics_endpoint(
                        db=session,
                        x_mnemox_ops_token="wrong-token",
                    )
                self.assertEqual(context.exception.status_code, 404)

                response = await metrics_endpoint(
                    db=session,
                    x_mnemox_ops_token="monitor-token",
                )
                self.assertIsNone(await session.get(policy_model, 1))

        body = response.body.decode("utf-8")
        self.assertEqual(response.media_type, "text/plain")
        self.assertIn("mnemox_projection_outbox_dead_letter_tasks 1", body)
        self.assertIn("mnemox_projection_outbox_retry_policy_initialized 0", body)
        self.assertIn(
            'mnemox_projection_outbox_alert{code="projection_outbox_retry_policy_uninitialized"} 1',
            body,
        )
        self.assertIn('mnemox_projection_outbox_alert{code="projection_outbox_dead_letter"} 1', body)
        self.assertNotIn("owner failure should stay private", body)
        self.assertNotIn("user_id", body)
        self.assertNotIn("payload", body)

    async def test_failure_queue_api_hides_other_users_and_allows_owned_retry(self):
        owner_row = await self._create_outbox_row(self.owner, self.owner_concept, "api-owner")
        other_row = await self._create_outbox_row(self.other, self.other_concept, "api-other")
        await self._mark_failed(owner_row, attempts=5)
        await self._mark_failed(other_row, attempts=5)

        failed_tasks = getattr(learner_model_router, "outbox_failed_tasks", None)
        retry_failed_task = getattr(learner_model_router, "retry_outbox_failed_task", None)
        self.assertIsNotNone(failed_tasks)
        self.assertIsNotNone(retry_failed_task)

        async with self.sessions() as session:
            queue = await failed_tasks(
                offset=0,
                limit=50,
                db=session,
                current_user=self.owner,
            )
            self.assertEqual(queue["total"], 1)
            self.assertEqual([item["id"] for item in queue["items"]], [owner_row])
            self.assertNotIn("last_error", queue["items"][0])
            self.assertNotIn("payload", queue["items"][0])

            with self.assertRaises(HTTPException) as context:
                await retry_failed_task(
                    other_row,
                    db=session,
                    current_user=self.owner,
                )
            self.assertEqual(context.exception.status_code, 404)

            retry = await retry_failed_task(
                owner_row,
                db=session,
                current_user=self.owner,
            )
            self.assertEqual(retry["status"], "pending")


if __name__ == "__main__":
    unittest.main()
