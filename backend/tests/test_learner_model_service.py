"""Learner-model evidence, replay, manual correction, and isolation tests."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept, ConceptLink
from app.models.learner_model import LearnerEvidence, UserConceptState
from app.models.material import Chapter, Material
from app.models.question import ReviewSchedule
from app.models.user import User
from app.routers.review import (
    ReviewCompleteRequest,
    ReviewSubmitRequest,
    complete_review_task,
    submit_review_answers,
)
from app.services.learning_event_service import record_learning_event
from app.services.concept_service import list_concepts
from app.services.learner_model_service import (
    apply_manual_override,
    get_concept_state,
    recompute_concept_state,
    record_evidence,
    record_review_result_evidence,
)


class LearnerModelServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "learner_model.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        # Keep fixture events safely in the past so current-state replay does
        # not intentionally discard them as future-dated observations.
        self.now = datetime.now().replace(microsecond=0) - timedelta(days=1)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    async def _create_concept(self, user_id: int, name: str = "条件概率") -> int:
        async with self.sessionmaker() as session:
            concept = Concept(
                user_id=user_id,
                name=name,
                name_normalized=name.lower(),
                mastery=12.0,
                source="test",
            )
            session.add(concept)
            await session.flush()
            concept_id = int(concept.id)
            await session.commit()
            return concept_id

    async def _event(self, session, user_id: int, event_type: str, occurred_at: datetime):
        return await record_learning_event(
            session,
            user_id,
            event_type,
            source="test",
            payload={"concept_id": 1},
            occurred_at=occurred_at,
        )

    async def test_direct_evidence_drives_mastery_but_indirect_signal_does_not(self):
        user_id = await self._create_user("direct-owner")
        concept_id = await self._create_concept(user_id)
        indirect_only_concept_id = await self._create_concept(user_id, "随机变量")

        async with self.sessionmaker() as session:
            answer_event = await self._event(session, user_id, "practice.answer", self.now)
            first = await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=0.8,
                reliability=0.9,
                source_event_id=answer_event["id"],
                source_type="practice",
                source_id="answer-1",
                dimension="recall",
                observed_at=self.now,
            )
            mastery_after_direct = first["state"]["mastery_estimate"]

            duration_event = await self._event(
                session, user_id, "study.duration", self.now + timedelta(minutes=1)
            )
            second = await record_evidence(
                session,
                user_id,
                concept_id,
                "study_duration",
                score=1.0,
                reliability=1.0,
                source_event_id=duration_event["id"],
                source_type="pomodoro",
                source_id="session-1",
                observed_at=self.now + timedelta(minutes=1),
            )
            indirect_only_event = await self._event(
                session, user_id, "study.frequency", self.now + timedelta(minutes=2)
            )
            indirect_only = await record_evidence(
                session,
                user_id,
                indirect_only_concept_id,
                "study_frequency",
                score=1.0,
                reliability=1.0,
                source_event_id=indirect_only_event["id"],
                source_type="analytics",
                observed_at=self.now + timedelta(minutes=2),
            )
            concept_row = await session.get(Concept, concept_id)
            concept_items = await list_concepts(session, user_id)
            await session.commit()

        self.assertAlmostEqual(second["state"]["mastery_estimate"], mastery_after_direct, places=4)
        self.assertGreater(second["state"]["confidence"], 0.0)
        self.assertIn("study_duration", second["state"]["explanation_summary"]["indirect_effects"])
        self.assertEqual(second["evidence"]["evidence_category"], "indirect")
        self.assertEqual(indirect_only["state"]["mastery_estimate"], 0.0)
        self.assertEqual(indirect_only["state"]["explanation_summary"]["indirect_mastery_delta"], 0.0)
        self.assertEqual(concept_row.mastery, 12.0)
        concept_item = next(item for item in concept_items if item["id"] == concept_id)
        self.assertAlmostEqual(concept_item["mastery"], mastery_after_direct, places=4)
        self.assertEqual(concept_item["mastery_source"], "user_concept_state")

    async def test_review_projection_keeps_event_source_and_schedule_reason(self):
        user_id = await self._create_user("review-owner")
        concept_id = await self._create_concept(user_id)
        async with self.sessionmaker() as session:
            session.add(
                ConceptLink(
                    user_id=user_id,
                    concept_id=concept_id,
                    target_type="chapter",
                    target_id=42,
                    link_type="covers",
                )
            )
            event = await self._event(session, user_id, "review.completed", self.now)
            count = await record_review_result_evidence(
                session,
                user_id,
                target_type="chapter",
                target_id=42,
                quality=4,
                source_event_id=event["id"],
                observed_at=self.now,
                next_review_at=self.now + timedelta(days=3),
            )
            await session.commit()

        self.assertEqual(count, 1)
        async with self.sessionmaker() as session:
            evidence = (await session.execute(select(LearnerEvidence))).scalar_one()
            state = (await session.execute(select(UserConceptState))).scalar_one()
        self.assertEqual(evidence.source_event_id, event["id"])
        self.assertEqual(evidence.evidence_type, "review_result")
        self.assertAlmostEqual(evidence.score, 0.8)
        self.assertEqual(state.source_event_id, event["id"])
        self.assertGreater(state.reliability, 0.0)
        self.assertEqual(state.model_version, "explainable-rules-v1")
        self.assertIsNotNone(state.updated_at)
        self.assertEqual(state.next_review_at, self.now + timedelta(days=3))
        self.assertEqual(state.explanation_summary["rule"], "reliability_weighted_score_with_90_day_decay")

    async def test_historical_replay_excludes_evidence_observed_after_as_of(self):
        user_id = await self._create_user("replay-time-owner")
        concept_id = await self._create_concept(user_id)
        historical_at = self.now - timedelta(days=1)
        async with self.sessionmaker() as session:
            first_event = await self._event(session, user_id, "practice.answer", historical_at)
            await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=1.0,
                reliability=1.0,
                source_event_id=first_event["id"],
                source_type="practice",
                observed_at=historical_at,
            )
            later_event = await self._event(session, user_id, "practice.answer", self.now)
            current = await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=0.0,
                reliability=1.0,
                source_event_id=later_event["id"],
                source_type="practice",
                observed_at=self.now,
            )
            historical = await recompute_concept_state(
                session, user_id, concept_id, as_of=historical_at
            )
            stored = await session.get(UserConceptState, {"user_id": user_id, "concept_id": concept_id})
            await session.commit()

        self.assertAlmostEqual(historical["mastery_estimate"], 100.0, places=4)
        self.assertEqual(historical["explanation_summary"]["direct_evidence_count"], 1)
        self.assertLess(current["state"]["mastery_estimate"], historical["mastery_estimate"])
        self.assertIsNotNone(stored)
        self.assertAlmostEqual(stored.mastery_estimate, current["state"]["mastery_estimate"], places=4)

    async def test_timestamp_normalization_uses_local_naive_convention(self):
        user_id = await self._create_user("time-owner")
        concept_id = await self._create_concept(user_id)
        aware_utc = datetime(2026, 8, 4, 4, 0, tzinfo=timezone.utc)
        expected_local = aware_utc.astimezone().replace(tzinfo=None)
        async with self.sessionmaker() as session:
            source_event = await self._event(session, user_id, "practice.answer", aware_utc)
            result = await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=0.8,
                reliability=1.0,
                source_event_id=source_event["id"],
                source_type="practice",
                observed_at=aware_utc,
            )
            await session.commit()

        self.assertEqual(result["evidence"]["observed_at"], expected_local.isoformat())

    async def test_existing_review_route_projects_learning_event_inline(self):
        user_id = await self._create_user("route-owner")
        concept_id = await self._create_concept(user_id)
        async with self.sessionmaker() as session:
            user = await session.get(User, user_id)
            material = Material(user_id=user_id, title="概率论", content="内容")
            session.add(material)
            await session.flush()
            chapter = Chapter(
                material_id=material.id,
                title="条件概率",
                content="章节内容",
                mastery_level=10.0,
            )
            session.add(chapter)
            await session.flush()
            session.add(
                ConceptLink(
                    user_id=user_id,
                    concept_id=concept_id,
                    target_type="chapter",
                    target_id=chapter.id,
                    link_type="covers",
                )
            )
            schedule = ReviewSchedule(
                user_id=user_id,
                item_type="chapter",
                item_id=chapter.id,
                scheduled_date=self.now,
                interval_days=1,
                ease_factor=250,
                repetitions=0,
                status="pending",
            )
            session.add(schedule)
            await session.flush()

            await complete_review_task(
                int(schedule.id),
                ReviewCompleteRequest(quality=4),
                db=session,
                current_user=user,
            )
            state_after_request = await session.get(
                UserConceptState, {"user_id": user_id, "concept_id": concept_id}
            )
            self.assertIsNotNone(state_after_request)
            await session.commit()

        async with self.sessionmaker() as session:
            evidence = await session.scalar(
                select(LearnerEvidence).where(
                    LearnerEvidence.user_id == user_id,
                    LearnerEvidence.concept_id == concept_id,
                    LearnerEvidence.evidence_type == "review_result",
                )
            )
            state = await session.get(
                UserConceptState, {"user_id": user_id, "concept_id": concept_id}
            )
        self.assertIsNotNone(evidence)
        self.assertIsNotNone(evidence.source_event_id)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state.mastery_estimate, 80.0, places=4)
        self.assertEqual(state.last_reviewed_at, evidence.observed_at)

    async def test_ai_review_scores_are_clamped_before_learner_projection(self):
        user_id = await self._create_user("ai-review-owner")
        concept_id = await self._create_concept(user_id)
        async with self.sessionmaker() as session:
            user = await session.get(User, user_id)
            material = Material(user_id=user_id, title="概率论", content="内容")
            session.add(material)
            await session.flush()
            chapter = Chapter(material_id=material.id, title="条件概率", content="章节内容")
            session.add(chapter)
            await session.flush()
            session.add(
                ConceptLink(
                    user_id=user_id,
                    concept_id=concept_id,
                    target_type="chapter",
                    target_id=chapter.id,
                    link_type="covers",
                )
            )
            schedule = ReviewSchedule(
                user_id=user_id,
                item_type="chapter",
                item_id=chapter.id,
                scheduled_date=self.now,
                interval_days=1,
                ease_factor=250,
                repetitions=0,
                status="pending",
            )
            session.add(schedule)
            await session.flush()

            class _Provider:
                async def chat(self, _messages):
                    return '{"score": 125, "quality": 6, "feedback": "夸大评分"}'

            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(return_value=_Provider()),
            ):
                result = await submit_review_answers(
                    int(schedule.id),
                    ReviewSubmitRequest(answers=[]),
                    db=session,
                    current_user=user,
                )
            await session.commit()

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["quality"], 5)
        async with self.sessionmaker() as session:
            evidence = await session.scalar(
                select(LearnerEvidence).where(
                    LearnerEvidence.user_id == user_id,
                    LearnerEvidence.concept_id == concept_id,
                    LearnerEvidence.evidence_type == "review_result",
                )
            )
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence.payload["quality"], 5)

    async def test_sqlite_foreign_keys_cascade_concept_learner_rows(self):
        user_id = await self._create_user("cascade-owner")
        concept_id = await self._create_concept(user_id)
        async with self.engine.connect() as connection:
            self.assertEqual(await connection.scalar(text("PRAGMA foreign_keys")), 1)

        async with self.sessionmaker() as session:
            source_event = await self._event(session, user_id, "practice.answer", self.now)
            await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=0.7,
                reliability=1.0,
                source_event_id=source_event["id"],
                source_type="practice",
                observed_at=self.now,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            concept = await session.get(Concept, concept_id)
            await session.delete(concept)
            await session.commit()

        async with self.sessionmaker() as session:
            evidence_count = await session.scalar(
                select(func.count()).select_from(LearnerEvidence).where(
                    LearnerEvidence.concept_id == concept_id
                )
            )
            state_count = await session.scalar(
                select(func.count()).select_from(UserConceptState).where(
                    UserConceptState.concept_id == concept_id
                )
            )
        self.assertEqual(evidence_count, 0)
        self.assertEqual(state_count, 0)

    async def test_manual_override_survives_recompute_until_cleared(self):
        user_id = await self._create_user("manual-owner")
        concept_id = await self._create_concept(user_id)
        async with self.sessionmaker() as session:
            answer_event = await self._event(session, user_id, "practice.answer", self.now)
            await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=0.2,
                reliability=0.9,
                source_event_id=answer_event["id"],
                source_type="practice",
                observed_at=self.now,
            )
            override = await apply_manual_override(
                session,
                user_id,
                concept_id,
                mastery_estimate=88.0,
                reason="教师确认已掌握",
                occurred_at=self.now + timedelta(minutes=1),
            )
            new_event = await self._event(
                session, user_id, "practice.answer", self.now + timedelta(minutes=2)
            )
            after_new_evidence = await record_evidence(
                session,
                user_id,
                concept_id,
                "answer",
                score=0.1,
                reliability=0.9,
                source_event_id=new_event["id"],
                source_type="practice",
                observed_at=self.now + timedelta(minutes=2),
            )
            self.assertEqual(after_new_evidence["state"]["mastery_estimate"], 88.0)
            self.assertTrue(after_new_evidence["state"]["explanation_summary"]["manual_override_active"])

            cleared = await apply_manual_override(
                session,
                user_id,
                concept_id,
                mastery_estimate=None,
                reason="撤销旧的人工修正",
                occurred_at=self.now + timedelta(minutes=3),
            )
            await session.commit()

        self.assertEqual(override["state"]["source_event_id"], override["evidence"]["source_event_id"])
        self.assertIsNone(cleared["state"]["manual_override"])
        self.assertNotEqual(cleared["state"]["mastery_estimate"], 88.0)

    async def test_state_can_be_deleted_and_rebuilt_from_evidence(self):
        user_id = await self._create_user("replay-owner")
        concept_id = await self._create_concept(user_id)
        async with self.sessionmaker() as session:
            event = await self._event(session, user_id, "practice.recall", self.now)
            result = await record_evidence(
                session,
                user_id,
                concept_id,
                "recall",
                score=0.75,
                reliability=0.8,
                source_event_id=event["id"],
                source_type="practice",
                observed_at=self.now,
            )
            expected = result["state"]
            await session.execute(
                delete(UserConceptState).where(
                    UserConceptState.user_id == user_id,
                    UserConceptState.concept_id == concept_id,
                )
            )
            rebuilt = await get_concept_state(session, user_id, concept_id)
            await session.commit()

        self.assertEqual(rebuilt["mastery_estimate"], expected["mastery_estimate"])
        self.assertEqual(rebuilt["source_event_id"], event["id"])
        self.assertEqual(rebuilt["explanation_summary"]["direct_evidence_count"], 1)

    async def test_get_state_refreshes_time_dependent_risk(self):
        user_id = await self._create_user("stale-state-owner")
        concept_id = await self._create_concept(user_id)
        observed_at = self.now - timedelta(days=180)
        async with self.sessionmaker() as session:
            source_event = await self._event(session, user_id, "practice.recall", observed_at)
            await record_evidence(
                session,
                user_id,
                concept_id,
                "recall",
                score=1.0,
                reliability=1.0,
                source_event_id=source_event["id"],
                source_type="practice",
                observed_at=observed_at,
            )
            await session.execute(
                update(UserConceptState)
                .where(
                    UserConceptState.user_id == user_id,
                    UserConceptState.concept_id == concept_id,
                )
                .values(forgetting_risk=0.0)
            )
            refreshed = await get_concept_state(session, user_id, concept_id)
            await session.commit()

        self.assertGreater(refreshed["forgetting_risk"], 0.15)

    async def test_hint_dependence_is_inverted_before_affecting_mastery(self):
        user_id = await self._create_user("hint-owner")
        concept_id = await self._create_concept(user_id)
        async with self.sessionmaker() as session:
            event = await self._event(session, user_id, "practice.hints", self.now)
            result = await record_evidence(
                session,
                user_id,
                concept_id,
                "hint_count",
                score=0.8,
                reliability=1.0,
                source_event_id=event["id"],
                source_type="practice",
                observed_at=self.now,
            )
            await session.commit()

        self.assertAlmostEqual(result["state"]["mastery_estimate"], 20.0, places=4)
        self.assertIn("hint_count is inverted", result["state"]["explanation_summary"]["score_semantics"])

    async def test_concept_and_source_event_are_user_scoped(self):
        owner_id = await self._create_user("scope-owner")
        other_id = await self._create_user("scope-other")
        owner_concept_id = await self._create_concept(owner_id)
        async with self.sessionmaker() as session:
            other_event = await self._event(session, other_id, "practice.answer", self.now)
            with self.assertRaises(LookupError):
                await record_evidence(
                    session,
                    other_id,
                    owner_concept_id,
                    "answer",
                    score=1.0,
                    reliability=1.0,
                    source_event_id=other_event["id"],
                    source_type="practice",
                    observed_at=self.now,
                )
            with self.assertRaises(LookupError):
                await get_concept_state(session, other_id, owner_concept_id)
            with self.assertRaises(LookupError):
                await record_evidence(
                    session,
                    owner_id,
                    owner_concept_id,
                    "answer",
                    score=1.0,
                    reliability=1.0,
                    source_event_id=other_event["id"],
                    source_type="practice",
                    observed_at=self.now,
                )


if __name__ == "__main__":
    unittest.main()
