"""Lifecycle tests for the durable projection outbox worker."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import main
from app.config import Settings
from app.models import learner_model as learner_model_models
from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept
from app.models.learner_model import ProjectionOutbox
from app.models.user import User
from app.main import app, health
from app.services.learning_event_service import record_learning_event
from app.services.projection_outbox_service import (
    get_outbox_operations_snapshot,
    resolve_outbox_retry_policy,
)
from app.services.projection_outbox_worker import ProjectionOutboxWorker, default_worker_id


class ProjectionOutboxWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "outbox-worker.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.worker_commit_calls = 0
        test_case = self

        class CountingAsyncSession(AsyncSession):
            async def commit(self) -> None:
                test_case.worker_commit_calls += 1
                await super().commit()

        self.sessions = async_sessionmaker(
            self.engine,
            class_=CountingAsyncSession,
            expire_on_commit=False,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_pending_projection(
        self,
        name: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> int:
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
                user_id=user.id,
                name=name,
                name_normalized=name,
                mastery=0,
                source="test",
            )
            session.add(concept)
            await session.flush()
            event_payload = {"concept_id": int(concept.id), "score": 0.75}
            if payload:
                event_payload.update(payload)
            event_item = await record_learning_event(
                session,
                int(user.id),
                "practice.answer",
                source="test",
                payload=event_payload,
                occurred_at=datetime.now() - timedelta(minutes=1),
            )
            await session.commit()
            row = await session.scalar(
                select(ProjectionOutbox).where(
                    ProjectionOutbox.source_event_id == int(event_item["id"])
                )
            )
            self.assertIsNotNone(row)
            return int(row.id)

    async def _wait_until_processed(self, outbox_id: int) -> None:
        async def is_processed() -> bool:
            async with self.sessions() as session:
                row = await session.get(ProjectionOutbox, outbox_id)
                return row is not None and row.status == "processed"

        for _ in range(50):
            if await is_processed():
                return
            await asyncio.sleep(0.01)
        self.fail("worker did not process the queued projection")

    def test_heartbeat_settings_require_scheduling_headroom(self):
        with self.assertRaises(ValidationError):
            Settings(
                OUTBOX_WORKER_ENABLED=True,
                OUTBOX_WORKER_HEARTBEAT_INTERVAL_SECONDS=60,
                OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS=74,
            )

        valid = Settings(
            OUTBOX_WORKER_ENABLED=True,
            OUTBOX_WORKER_HEARTBEAT_INTERVAL_SECONDS=60,
            OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS=75,
        )
        self.assertEqual(valid.OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS, 75)

    def test_default_worker_id_fits_heartbeat_storage_for_long_host_and_prefix(self):
        with patch(
            "app.services.projection_outbox_worker.socket.gethostname",
            return_value="host-" + "h" * 240,
        ):
            worker_id = default_worker_id("deployment-" + "p" * 240)

        self.assertLessEqual(len(worker_id), 120)
        self.assertTrue(worker_id.startswith("deployment-"))
        self.assertRegex(worker_id, r":\d+:[0-9a-f]{12}$")

    async def test_run_once_commits_projection_and_records_runtime_stats(self):
        outbox_id = await self._create_pending_projection("worker-once")
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="test-worker",
            batch_size=10,
            max_attempts=5,
            poll_interval_seconds=0.01,
        )

        result = await worker.run_once()

        self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
        snapshot = worker.snapshot()
        self.assertEqual(snapshot["worker_id"], "test-worker")
        self.assertEqual(snapshot["polls"], 1)
        self.assertEqual(snapshot["claimed"], 1)
        self.assertEqual(snapshot["processed"], 1)
        self.assertEqual(snapshot["failed"], 0)
        self.assertIsNone(snapshot["last_error"])
        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertEqual(row.status, "processed")

    async def test_run_once_uses_the_shared_retry_policy_after_a_version_upgrade(self):
        outbox_id = await self._create_pending_projection("worker-retry-policy-upgrade")
        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertIsNotNone(row)
            row.status = "failed"
            row.attempts = 5
            row.available_at = datetime.now() - timedelta(seconds=1)
            await session.commit()

        old_worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="retry-policy-v1-worker",
            batch_size=1,
            max_attempts=3,
            retry_policy_version=1,
            poll_interval_seconds=0.01,
        )
        self.assertEqual(
            await old_worker.run_once(),
            {"claimed": 0, "processed": 0, "failed": 0},
        )

        upgraded_worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="retry-policy-v2-worker",
            batch_size=1,
            max_attempts=10,
            retry_policy_version=2,
            poll_interval_seconds=0.01,
        )
        self.assertEqual(
            await upgraded_worker.run_once(),
            {"claimed": 1, "processed": 1, "failed": 0},
        )

        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertEqual(row.status, "processed")
            self.assertIsNone(row.dead_lettered_at)

    async def test_worker_refreshes_the_policy_for_each_claim_after_an_upgrade(self):
        outbox_id = await self._create_pending_projection(
            "worker-retry-policy-refresh",
            payload={"score": "not-a-number"},
        )
        old_worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="retry-policy-refresh-v1-worker",
            batch_size=1,
            max_attempts=3,
            retry_policy_version=1,
            poll_interval_seconds=0.01,
        )
        await old_worker._reconcile_terminal_failures()

        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertIsNotNone(row)
            row.status = "failed"
            row.attempts = 2
            row.available_at = datetime.now() - timedelta(seconds=1)
            await session.commit()

        async with self.sessions() as session:
            effective_max_attempts = await resolve_outbox_retry_policy(
                session,
                max_attempts=10,
                retry_policy_version=2,
            )
            self.assertEqual(effective_max_attempts, 10)
            await session.commit()

        result = await old_worker._process_one_row()
        self.assertEqual(result, {"claimed": 1, "processed": 0, "failed": 1})

        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertIsNotNone(row)
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.attempts, 3)
            self.assertIsNone(row.dead_lettered_at)

    async def test_run_once_commits_each_claimed_row_in_its_own_transaction(self):
        await self._create_pending_projection("worker-first")
        await self._create_pending_projection("worker-second")
        self.worker_commit_calls = 0
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="per-row-worker",
            batch_size=10,
            max_attempts=5,
            poll_interval_seconds=0.01,
        )
        await worker._reconcile_terminal_failures()
        self.worker_commit_calls = 0

        result = await worker.run_once()

        self.assertEqual(result, {"claimed": 2, "processed": 2, "failed": 0})
        self.assertEqual(self.worker_commit_calls, 2)

    async def test_run_once_records_durable_projection_failure_in_health_snapshot(self):
        outbox_id = await self._create_pending_projection(
            "worker-projection-failure",
            payload={"score": "not-a-number"},
        )
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="projection-failure-worker",
            batch_size=10,
            max_attempts=5,
            poll_interval_seconds=0.01,
        )

        result = await worker.run_once()

        self.assertEqual(result, {"claimed": 1, "processed": 0, "failed": 1})
        snapshot = worker.snapshot()
        self.assertEqual(snapshot["failed"], 1)
        self.assertIsNotNone(snapshot["last_projection_failure_at"])
        self.assertIsNotNone(snapshot["last_error_at"])
        self.assertEqual(snapshot["last_error"], "one or more projection rows failed")
        self.assertEqual(snapshot["last_error_code"], "projection_outbox.worker_failed")
        self.assertRegex(snapshot["last_error_fingerprint"], r"^[0-9a-f]{16}$")
        health_snapshot = worker.health_snapshot()
        self.assertEqual(
            health_snapshot["last_projection_failure_at"],
            snapshot["last_projection_failure_at"],
        )
        self.assertNotIn("last_error", health_snapshot)
        self.assertEqual(
            health_snapshot["last_error_code"],
            "projection_outbox.worker_failed",
        )
        async with self.sessions() as session:
            row = await session.get(ProjectionOutbox, outbox_id)
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.attempts, 1)

    async def test_started_worker_consumes_backlog_and_stops_without_waiting_for_next_poll(self):
        outbox_id = await self._create_pending_projection("worker-loop")
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="test-worker-loop",
            batch_size=10,
            max_attempts=5,
            poll_interval_seconds=30,
        )

        worker.start()
        await self._wait_until_processed(outbox_id)
        await asyncio.wait_for(worker.stop(), timeout=1)

        snapshot = worker.snapshot()
        self.assertFalse(snapshot["running"])
        self.assertGreaterEqual(snapshot["polls"], 1)
        self.assertGreaterEqual(snapshot["processed"], 1)

    async def test_enabled_worker_persists_heartbeat_and_marks_graceful_stop(self):
        heartbeat_model = getattr(
            learner_model_models,
            "ProjectionOutboxWorkerHeartbeat",
            None,
        )
        self.assertIsNotNone(heartbeat_model)
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="heartbeat-worker",
            batch_size=1,
            max_attempts=5,
            poll_interval_seconds=0.01,
            heartbeat_enabled=True,
            heartbeat_interval_seconds=0.01,
        )

        worker.start()
        for _ in range(50):
            async with self.sessions() as session:
                heartbeat = await session.get(heartbeat_model, "heartbeat-worker")
                if heartbeat is not None and heartbeat.last_heartbeat_at is not None:
                    break
            await asyncio.sleep(0.01)
        else:
            self.fail("worker did not persist a heartbeat")

        await asyncio.wait_for(worker.stop(), timeout=1)
        async with self.sessions() as session:
            heartbeat = await session.get(heartbeat_model, "heartbeat-worker")
            self.assertIsNotNone(heartbeat)
            self.assertIsNotNone(heartbeat.stopped_at)

    async def test_configured_worker_prefix_uses_unique_heartbeats_per_runtime(self):
        heartbeat_model = getattr(
            learner_model_models,
            "ProjectionOutboxWorkerHeartbeat",
            None,
        )
        self.assertIsNotNone(heartbeat_model)
        await self._create_pending_projection("configured-worker-prefix")

        with patch.object(
            main.settings,
            "OUTBOX_WORKER_ID",
            "deployment-worker",
            create=True,
        ):
            stopped_worker = main.create_projection_outbox_worker(self.sessions)
            active_worker = main.create_projection_outbox_worker(self.sessions)

        self.assertNotEqual(stopped_worker.worker_id, active_worker.worker_id)
        self.assertTrue(stopped_worker.worker_id.startswith("deployment-worker:"))
        self.assertTrue(active_worker.worker_id.startswith("deployment-worker:"))

        await stopped_worker._persist_heartbeat(force=True)
        await active_worker._persist_heartbeat(force=True)
        await stopped_worker.stop()

        async with self.sessions() as session:
            stopped_heartbeat = await session.get(heartbeat_model, stopped_worker.worker_id)
            active_heartbeat = await session.get(heartbeat_model, active_worker.worker_id)
            snapshot = await get_outbox_operations_snapshot(
                session,
                heartbeat_ttl_seconds=60,
                worker_expected=True,
            )

        self.assertIsNotNone(stopped_heartbeat)
        self.assertIsNotNone(stopped_heartbeat.stopped_at)
        self.assertIsNotNone(active_heartbeat)
        self.assertIsNone(active_heartbeat.stopped_at)
        self.assertEqual(snapshot["metrics"]["known_workers"], 2)
        self.assertEqual(snapshot["metrics"]["active_workers"], 1)
        self.assertNotIn(
            "projection_outbox_no_active_worker",
            {alert["code"] for alert in snapshot["alerts"]},
        )

    async def test_enabled_worker_records_first_poll_error_without_waiting_for_heartbeat_interval(self):
        heartbeat_model = getattr(
            learner_model_models,
            "ProjectionOutboxWorkerHeartbeat",
            None,
        )
        self.assertIsNotNone(heartbeat_model)
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="heartbeat-error-worker",
            batch_size=1,
            max_attempts=5,
            poll_interval_seconds=0.01,
            heartbeat_enabled=True,
            heartbeat_interval_seconds=60,
            heartbeat_ttl_seconds=75,
        )

        async def failing_process_one_row() -> dict[str, int]:
            raise RuntimeError("database unavailable")

        worker._process_one_row = failing_process_one_row
        worker.start()
        try:
            for _ in range(50):
                async with self.sessions() as session:
                    heartbeat = await session.get(heartbeat_model, "heartbeat-error-worker")
                    if heartbeat is not None and heartbeat.last_error_at is not None:
                        break
                await asyncio.sleep(0.01)
            else:
                self.fail("worker did not persist its first poll error")
        finally:
            await asyncio.wait_for(worker.stop(), timeout=1)

    async def test_alert_scan_reports_retry_policy_config_conflict_without_resolving_policy(self):
        async with self.sessions() as session:
            effective_max_attempts = await resolve_outbox_retry_policy(
                session,
                max_attempts=5,
                retry_policy_version=1,
            )
            self.assertEqual(effective_max_attempts, 5)
            await session.commit()

        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="retry-policy-conflict-alert-worker",
            batch_size=1,
            max_attempts=3,
            retry_policy_version=1,
            poll_interval_seconds=0.01,
            heartbeat_enabled=True,
        )

        await worker._emit_alert_transition()

        self.assertIn(
            "projection_outbox_retry_policy_config_conflict",
            worker._active_alert_codes,
        )

    async def test_enabled_worker_refreshes_heartbeat_while_poll_is_slow(self):
        heartbeat_model = getattr(
            learner_model_models,
            "ProjectionOutboxWorkerHeartbeat",
            None,
        )
        self.assertIsNotNone(heartbeat_model)
        started = asyncio.Event()
        release = asyncio.Event()
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="slow-heartbeat-worker",
            batch_size=1,
            max_attempts=5,
            poll_interval_seconds=30,
            heartbeat_enabled=True,
            heartbeat_interval_seconds=0.01,
        )

        async def slow_process_one_row() -> dict[str, int]:
            started.set()
            await release.wait()
            return {"claimed": 0, "processed": 0, "failed": 0}

        worker._process_one_row = slow_process_one_row
        worker.start()
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            for _ in range(50):
                async with self.sessions() as session:
                    heartbeat = await session.get(heartbeat_model, "slow-heartbeat-worker")
                    if heartbeat is not None:
                        first_heartbeat_at = heartbeat.last_heartbeat_at
                        break
                await asyncio.sleep(0.01)
            else:
                self.fail("worker did not persist an initial heartbeat")

            for _ in range(100):
                async with self.sessions() as session:
                    heartbeat = await session.get(heartbeat_model, "slow-heartbeat-worker")
                    if (
                        heartbeat is not None
                        and heartbeat.last_heartbeat_at > first_heartbeat_at
                    ):
                        break
                await asyncio.sleep(0.01)
            else:
                self.fail("worker did not refresh its heartbeat during a slow poll")
        finally:
            release.set()
            await asyncio.wait_for(worker.stop(), timeout=1)

    async def test_poll_exception_is_recorded_and_loop_remains_stoppable(self):
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="error-worker",
            batch_size=10,
            max_attempts=5,
            poll_interval_seconds=0.01,
        )
        original_factory = worker._session_factory

        class FailingFactory:
            def __call__(self):
                raise RuntimeError("database unavailable")

        worker._session_factory = FailingFactory()
        worker.start()
        for _ in range(50):
            if worker.snapshot()["failed_polls"] > 0:
                break
            await asyncio.sleep(0.01)
        await asyncio.wait_for(worker.stop(), timeout=1)
        worker._session_factory = original_factory

        snapshot = worker.snapshot()
        self.assertGreaterEqual(snapshot["failed_polls"], 1)
        self.assertIn("database unavailable", snapshot["last_error"])
        self.assertEqual(snapshot["last_error_code"], "projection_outbox.worker_failed")
        self.assertRegex(snapshot["last_error_fingerprint"], r"^[0-9a-f]{16}$")
        self.assertFalse(snapshot["running"])

    async def test_public_health_omits_global_outbox_operations_snapshot(self):
        worker = ProjectionOutboxWorker(
            self.sessions,
            worker_id="health-worker",
            batch_size=10,
            max_attempts=5,
            poll_interval_seconds=0.01,
        )
        previous = getattr(app.state, "projection_outbox_worker", None)
        app.state.projection_outbox_worker = worker
        try:
            with patch.object(main, "_is_sqlite", return_value=True):
                payload = await health()
        finally:
            app.state.projection_outbox_worker = previous

        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("projection_outbox", payload)
        self.assertFalse(payload["projection_outbox_worker"]["running"])
        self.assertEqual(
            set(payload["projection_outbox_worker"]),
            {"enabled", "running"},
        )

    async def test_lifespan_stops_worker_before_database_close(self):
        events: list[str] = []

        class LifecycleWorker:
            started = False
            worker_id = "lifecycle-worker"

            def start(self) -> None:
                self.started = True

            async def stop(self) -> None:
                events.append("worker")

            def snapshot(self) -> dict[str, object]:
                return {"running": self.started}

        worker = LifecycleWorker()
        test_app = FastAPI(lifespan=main.lifespan)

        async def close_database() -> None:
            events.append("database")

        with (
            patch.object(main, "init_db", new=AsyncMock()),
            patch.object(main, "close_db", new=close_database),
            patch.object(main, "ensure_data_dirs"),
            patch.object(main.settings, "OUTBOX_WORKER_ENABLED", True, create=True),
            patch.object(main, "_is_sqlite", return_value=False),
            patch.object(main.settings, "RAG_ENABLED", False),
            patch.object(main, "create_projection_outbox_worker", return_value=worker, create=True),
            patch("app.services.memory_service.decay_episodic_memories", new=AsyncMock(return_value=0)),
        ):
            async with test_app.router.lifespan_context(test_app):
                self.assertTrue(worker.started)
                self.assertIs(test_app.state.projection_outbox_worker, worker)

        self.assertEqual(events, ["worker", "database"])

    async def test_health_marks_sqlite_worker_as_disabled_single_consumer(self):
        with (
            patch.object(main.settings, "OUTBOX_WORKER_ENABLED", True, create=True),
            patch.object(main, "_is_sqlite", return_value=True),
        ):
            previous = getattr(app.state, "projection_outbox_worker", None)
            app.state.projection_outbox_worker = None
            try:
                payload = await health()
            finally:
                app.state.projection_outbox_worker = previous

        self.assertEqual(
            payload["projection_outbox_worker"],
            {
                "enabled": False,
                "running": False,
                "disabled_reason": "sqlite_single_consumer",
            },
        )

    async def test_health_degrades_when_required_postgres_worker_is_not_running(self):
        with (
            patch.object(main.settings, "OUTBOX_WORKER_ENABLED", True, create=True),
            patch.object(main, "_is_sqlite", return_value=False),
        ):
            previous = getattr(app.state, "projection_outbox_worker", None)
            app.state.projection_outbox_worker = None
            try:
                payload = await health()
            finally:
                app.state.projection_outbox_worker = previous

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(
            payload["projection_outbox_worker"],
            {"enabled": True, "running": False},
        )


if __name__ == "__main__":
    unittest.main()
