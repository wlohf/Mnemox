"""Learner-model API pagination, corrections, recompute and isolation."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept
from app.models.learner_model import ProjectionOutbox
from app.models.user import User
from app.routers.learner_model import (
    BatchRecomputeRequest,
    ManualOverrideRequest,
    ReplayRequest,
    clear_concept_override,
    concept_evidence,
    concept_state,
    recompute_batch,
    replay,
    set_concept_override,
)
from app.services.learner_model_service import record_evidence
from app.services.learning_event_service import record_learning_event


class LearnerModelApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "api.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime.now().replace(microsecond=0) - timedelta(hours=1)
        self.owner, self.owner_concept = await self._create("api-owner")
        self.other, self.other_concept = await self._create("api-other")

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create(self, name: str) -> tuple[User, int]:
        async with self.sessions() as session:
            user = User(username=name, email=f"{name}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            concept = Concept(user_id=user.id, name=name, name_normalized=name, mastery=0, source="test")
            session.add(concept)
            await session.flush()
            detached = User(id=int(user.id), username=name, email=user.email, hashed_password="hash", is_active=True)
            concept_id = int(concept.id)
            await session.commit()
            return detached, concept_id

    async def _evidence(self, score: float, minute: int) -> None:
        async with self.sessions() as session:
            item = await record_learning_event(
                session, int(self.owner.id), "practice.answer", source="test",
                payload={"score": score}, occurred_at=self.now + timedelta(minutes=minute),
            )
            await record_evidence(
                session, int(self.owner.id), self.owner_concept, "answer",
                score=score, reliability=1.0, source_event_id=int(item["id"]),
                source_type="test", observed_at=self.now + timedelta(minutes=minute),
            )
            await session.commit()

    async def test_state_evidence_pagination_override_and_clear(self):
        await self._evidence(0.2, 1)
        await self._evidence(0.8, 2)
        async with self.sessions() as session:
            page = await concept_evidence(
                self.owner_concept, offset=0, limit=1, evidence_category=None,
                evidence_type=None, start_at=None, end_at=None,
                db=session, current_user=self.owner,
            )
            self.assertEqual(page["total"], 2)
            self.assertEqual(len(page["items"]), 1)
            override = await set_concept_override(
                self.owner_concept, ManualOverrideRequest(mastery_estimate=91, reason="teacher check"),
                db=session, current_user=self.owner,
            )
            self.assertEqual(override["state"]["mastery_estimate"], 91)
            override_outbox = await session.scalar(
                select(ProjectionOutbox).where(
                    ProjectionOutbox.source_event_id == override["evidence"]["source_event_id"]
                )
            )
            self.assertEqual(override_outbox.status, "processed")
            cleared = await clear_concept_override(
                self.owner_concept, reason="remove", db=session, current_user=self.owner
            )
            self.assertIsNone(cleared["state"]["manual_override"])

    async def test_all_endpoints_hide_cross_user_concepts(self):
        async with self.sessions() as session:
            calls = [
                concept_state(self.owner_concept, db=session, current_user=self.other),
                concept_evidence(self.owner_concept, offset=0, limit=50, evidence_category=None, evidence_type=None, start_at=None, end_at=None, db=session, current_user=self.other),
                set_concept_override(self.owner_concept, ManualOverrideRequest(mastery_estimate=50, reason="bad"), db=session, current_user=self.other),
                replay(ReplayRequest(concept_id=self.owner_concept), db=session, current_user=self.other),
                recompute_batch(BatchRecomputeRequest(concept_ids=[self.owner_concept]), db=session, current_user=self.other),
            ]
            for call in calls:
                with self.assertRaises(HTTPException) as context:
                    await call
                self.assertEqual(context.exception.status_code, 404)

    async def test_replay_rejects_mixed_timezone_range(self):
        async with self.sessions() as session:
            with self.assertRaises(HTTPException) as context:
                await replay(
                    ReplayRequest(
                        concept_id=self.owner_concept,
                        start_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                        end_at=datetime(2026, 8, 2),
                    ),
                    db=session,
                    current_user=self.owner,
                )
            self.assertEqual(context.exception.status_code, 422)
            self.assertIn("时区", context.exception.detail)

    async def test_evidence_rejects_reversed_range(self):
        async with self.sessions() as session:
            with self.assertRaises(HTTPException) as context:
                await concept_evidence(
                    self.owner_concept,
                    offset=0,
                    limit=50,
                    evidence_category=None,
                    evidence_type=None,
                    start_at=datetime(2026, 8, 2),
                    end_at=datetime(2026, 8, 1),
                    db=session,
                    current_user=self.owner,
                )
            self.assertEqual(context.exception.status_code, 422)
            self.assertIn("start_at", context.exception.detail)

    def test_batch_recompute_rejects_non_positive_concept_ids(self):
        with self.assertRaises(ValueError):
            BatchRecomputeRequest(concept_ids=[self.owner_concept, 0])

    def test_batch_recompute_rejects_explicit_empty_scope(self):
        with self.assertRaises(ValueError):
            BatchRecomputeRequest(concept_ids=[])

    async def test_unscoped_batch_recompute_rejects_silent_truncation(self):
        async with self.sessions() as session:
            session.add_all(
                [
                    Concept(
                        user_id=int(self.owner.id),
                        name=f"bulk-concept-{index}",
                        name_normalized=f"bulk-concept-{index}",
                        mastery=0,
                        source="test",
                    )
                    for index in range(500)
                ]
            )
            await session.commit()

        async with self.sessions() as session:
            with self.assertRaises(HTTPException) as context:
                await recompute_batch(BatchRecomputeRequest(), db=session, current_user=self.owner)

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("500", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
