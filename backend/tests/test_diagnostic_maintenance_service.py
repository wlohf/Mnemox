"""Historical diagnostic cleanup remains explicit, bounded, and rollbackable."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app.models  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.agent import AgentExecutionLog, AgentJob
from app.models.learning_event import LearningEvent
from app.models.learner_model import ProjectionOutbox
from app.models.retrieval import RetrievalProjection
from app.models.user import User
from app.services.diagnostic_maintenance_service import sanitize_persisted_diagnostics


class _CountingAsyncSession(AsyncSession):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1
        await super().commit()


class DiagnosticMaintenanceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        database_path = Path(self.tmp.name) / "diagnostics.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(
            self.engine,
            class_=_CountingAsyncSession,
            expire_on_commit=False,
        )
        await self._seed_history()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _seed_history(self) -> None:
        async with self.sessions() as db:
            user = User(
                username="diagnostic-owner",
                email="diagnostic-owner@example.test",
                hashed_password="hash",
            )
            db.add(user)
            await db.flush()
            event = LearningEvent(
                user_id=int(user.id),
                event_type="test.failure",
                event_data={},
            )
            db.add(event)
            await db.flush()

            db.add_all(
                [
                    AgentJob(
                        id="failed-job",
                        user_id=int(user.id),
                        agent="chat",
                        task="run",
                        status="failed",
                        payload={"token": "business-payload-is-out-of-scope"},
                        summary="provider failed api_key=job-summary-secret",
                        result={
                            "error_code": "legacy.provider_failed",
                            "error_summary": "Authorization: Bearer result-secret",
                            "error_fingerprint": "legacy-fingerprint",
                            "error": "password=result-error-secret",
                            "payload": {"token": "nested-business-data-is-out-of-scope"},
                        },
                    ),
                    AgentJob(
                        id="completed-job",
                        user_id=int(user.id),
                        agent="chat",
                        task="run",
                        status="completed",
                        payload={},
                        summary="completed token=successful-business-summary",
                        result={},
                    ),
                    AgentExecutionLog(
                        id="failed-log",
                        user_id=int(user.id),
                        job_id="failed-job",
                        agent="chat",
                        status="failed",
                        message="Authorization: Bearer log-message-secret",
                        extra_metadata={
                            "reason": "access_token=log-metadata-secret",
                            "payload": {"password": "nested-log-data-is-out-of-scope"},
                        },
                    ),
                    AgentExecutionLog(
                        id="completed-log",
                        user_id=int(user.id),
                        job_id="completed-job",
                        agent="chat",
                        status="completed",
                        message="completed token=successful-log-message",
                    ),
                    ProjectionOutbox(
                        user_id=int(user.id),
                        source_event_id=int(event.id),
                        idempotency_key="diagnostic-cleanup-test",
                        projection_type="learner_state",
                        model_version="test-v1",
                        payload_version=1,
                        payload={},
                        status="failed",
                        last_error="projection api_key=outbox-secret",
                    ),
                    RetrievalProjection(
                        user_id=int(user.id),
                        source_type="material",
                        source_id=999,
                        backend="chroma",
                        status="failed",
                        last_operation="ingest",
                        source_version=1,
                        last_error="vector password=retrieval-secret",
                    ),
                ]
            )
            await db.commit()

    async def test_dry_run_reports_changes_without_mutating_rows(self) -> None:
        async with self.sessions() as db:
            report = await sanitize_persisted_diagnostics(
                db,
                dry_run=True,
                batch_size=1,
            )

            self.assertEqual(report.scanned_rows, 4)
            self.assertEqual(report.changed_rows, 4)
            self.assertEqual(report.changed_columns, 6)
            self.assertEqual(report.sources["agent_jobs"].scanned_rows, 1)
            self.assertEqual(db.commit_calls, 0)
            failed = await db.get(AgentJob, "failed-job")
            self.assertIn("job-summary-secret", failed.summary)
            self.assertIn("result-secret", failed.result["error_summary"])

    async def test_apply_is_caller_owned_rollbackable_and_idempotent(self) -> None:
        async with self.sessions() as db:
            report = await sanitize_persisted_diagnostics(
                db,
                dry_run=False,
                batch_size=1,
            )
            self.assertEqual(report.changed_rows, 4)
            self.assertEqual(db.commit_calls, 0)
            failed = await db.get(AgentJob, "failed-job")
            self.assertNotIn("job-summary-secret", failed.summary)
            await db.rollback()

        async with self.sessions() as db:
            failed = await db.get(AgentJob, "failed-job")
            self.assertIn("job-summary-secret", failed.summary)
            await sanitize_persisted_diagnostics(db, dry_run=False, batch_size=2)
            self.assertEqual(db.commit_calls, 0)
            await db.commit()
            self.assertEqual(db.commit_calls, 1)

        async with self.sessions() as db:
            failed = await db.get(AgentJob, "failed-job")
            completed = await db.get(AgentJob, "completed-job")
            failed_log = await db.get(AgentExecutionLog, "failed-log")
            completed_log = await db.get(AgentExecutionLog, "completed-log")
            outbox = await db.get(ProjectionOutbox, 1)
            retrieval = await db.get(RetrievalProjection, 1)

            for secret in (
                "job-summary-secret",
                "result-secret",
                "result-error-secret",
                "log-message-secret",
                "log-metadata-secret",
                "outbox-secret",
                "retrieval-secret",
            ):
                self.assertNotIn(
                    secret,
                    repr((failed.summary, failed.result, failed_log.message, failed_log.extra_metadata, outbox.last_error, retrieval.last_error)),
                )
            self.assertIn("[REDACTED]", failed.summary)
            self.assertRegex(failed.result["error_fingerprint"], r"^[0-9a-f]{16}$")
            self.assertNotEqual(failed.result["error_fingerprint"], "legacy-fingerprint")
            self.assertEqual(
                failed.payload["token"],
                "business-payload-is-out-of-scope",
            )
            self.assertEqual(
                failed.result["payload"]["token"],
                "nested-business-data-is-out-of-scope",
            )
            self.assertEqual(
                failed_log.extra_metadata["payload"]["password"],
                "nested-log-data-is-out-of-scope",
            )
            self.assertIn("successful-business-summary", completed.summary)
            self.assertIn("successful-log-message", completed_log.message)

            repeated = await sanitize_persisted_diagnostics(db, dry_run=False)
            self.assertEqual(repeated.changed_rows, 0)
            self.assertEqual(repeated.changed_columns, 0)

    async def test_batch_size_is_bounded(self) -> None:
        async with self.sessions() as db:
            for invalid in (0, 5001):
                with self.assertRaises(ValueError):
                    await sanitize_persisted_diagnostics(db, batch_size=invalid)


if __name__ == "__main__":
    unittest.main()
