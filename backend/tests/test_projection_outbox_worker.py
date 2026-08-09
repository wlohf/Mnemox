"""Lifecycle tests for the durable projection outbox worker."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import main
from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept
from app.models.learner_model import ProjectionOutbox
from app.models.user import User
from app.main import app, health
from app.services.learning_event_service import record_learning_event
from app.services.projection_outbox_worker import ProjectionOutboxWorker


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
        health_snapshot = worker.health_snapshot()
        self.assertEqual(
            health_snapshot["last_projection_failure_at"],
            snapshot["last_projection_failure_at"],
        )
        self.assertNotIn("last_error", health_snapshot)
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
        self.assertFalse(snapshot["running"])

    async def test_health_includes_non_sensitive_worker_runtime_snapshot(self):
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
            payload = await health()
        finally:
            app.state.projection_outbox_worker = previous

        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["projection_outbox_worker"]["running"])
        self.assertNotIn("worker_id", payload["projection_outbox_worker"])
        self.assertNotIn("last_error", payload["projection_outbox_worker"])

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


if __name__ == "__main__":
    unittest.main()
