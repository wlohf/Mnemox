"""Learner evidence counters and explainable, user-isolated learning decisions."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept, ConceptSourceEvidence
from app.models.goal import Goal
from app.models.learner_model import LearnerEvidence
from app.models.material import Chapter, Material
from app.models.question import ReviewSchedule
from app.models.user import User
from app.routers.learner_model import LearnerEvidenceRequest, add_concept_evidence, learning_recommendations
from app.routers.wrong_questions import (
    WrongQuestionCreate,
    WrongQuestionReview,
    create_wrong_question,
    delete_wrong_question,
    review_wrong_question,
)
from app.services.concept_graph_service import create_concept_relation
from app.services.concept_service import link_concept, upsert_concept
from app.services.learner_model_service import record_evidence
from app.services.learning_event_service import record_learning_event
from app.services.learning_recommendation_service import list_learning_recommendations
from app.services.projection_outbox_service import process_outbox


class LearningRecommendationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        database = Path(self.tmpdir.name) / "recommendations.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime.now().replace(microsecond=0)
        self.owner = await self._user("recommendation-owner")
        self.other = await self._user("recommendation-other")

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _user(self, name: str) -> User:
        async with self.sessions() as session:
            user = User(username=name, email=f"{name}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            detached = User(id=int(user.id), username=name, email=user.email, hashed_password="hash", is_active=True)
            await session.commit()
            return detached

    async def _record(self, session, concept_id: int, evidence_type: str, score: float, *, payload=None):
        event_type = "study.duration" if evidence_type == "study_duration" else f"practice.{evidence_type}"
        item = await record_learning_event(
            session, int(self.owner.id), event_type, source="test",
            payload={"concept_id": concept_id, "score": score, **(payload or {})},
            occurred_at=self.now - timedelta(days=1),
        )
        return await record_evidence(
            session, int(self.owner.id), concept_id, evidence_type,
            score=score, reliability=0.9, source_event_id=int(item["id"]),
            source_type="test", observed_at=self.now - timedelta(days=1), payload=payload,
        )

    async def test_direct_counts_and_indirect_signals_do_not_manufacture_mastery(self):
        async with self.sessions() as session:
            concept = await upsert_concept(session, int(self.owner.id), "RRF")
            weak_only = await self._record(session, int(concept.id), "study_duration", 1.0)
            self.assertEqual(weak_only["state"]["mastery_estimate"], 0)
            self.assertEqual(weak_only["state"]["attempt_count"], 0)

            await self._record(session, int(concept.id), "answer", 0.2, payload={"error_type": "混淆重排顺序"})
            await self._record(session, int(concept.id), "recall", 0.9)
            result = await self._record(session, int(concept.id), "hint_count", 0.7, payload={"hint_count": 2})
            self.assertEqual(result["state"]["attempt_count"], 2)
            self.assertEqual(result["state"]["correct_count"], 1)
            self.assertEqual(result["state"]["hint_count"], 2)
            self.assertEqual(result["state"]["common_error_type"], "混淆重排顺序")

    async def test_recommendations_use_prerequisites_goals_fsrs_and_explain_scores(self):
        async with self.sessions() as session:
            material = Material(user_id=int(self.owner.id), title="混合检索教材", content="普通正文")
            session.add(material)
            await session.flush()
            chapter = Chapter(material_id=int(material.id), title="混合检索", content="普通正文", order_index=1)
            session.add(chapter)
            await session.flush()
            session.add(Goal(
                user_id=int(self.owner.id), material_id=int(material.id), title="掌握混合检索",
                status="active", deadline=(self.now + timedelta(days=3)).date(),
            ))
            session.add(ReviewSchedule(
                user_id=int(self.owner.id), item_type="chapter", item_id=int(chapter.id),
                scheduled_date=self.now - timedelta(hours=2), status="pending",
                is_archived=False, stability=2.5,
            ))
            prerequisite = await upsert_concept(session, int(self.owner.id), "混合检索")
            target = await upsert_concept(session, int(self.owner.id), "RRF")
            pending = await upsert_concept(
                session, int(self.owner.id), "未确认候选", source="material_extract", review_status="pending",
            )
            foreign = await upsert_concept(session, int(self.other.id), "外部用户概念")
            await link_concept(session, int(self.owner.id), int(prerequisite.id), "chapter", int(chapter.id))
            await link_concept(session, int(self.owner.id), int(target.id), "material", int(material.id))
            await create_concept_relation(
                session, int(self.owner.id), int(prerequisite.id), int(target.id), "prerequisite_of",
            )
            await self._record(session, int(target.id), "answer", 0.2, payload={"error_type": "混淆 reranker"})
            await session.flush()

            result = await list_learning_recommendations(session, int(self.owner.id), limit=20, as_of=self.now)
            gaps = [item for item in result["items"] if item["task_type"] == "prerequisite_gap"]
            self.assertTrue(gaps)
            self.assertEqual(gaps[0]["concept_id"], int(prerequisite.id))
            self.assertEqual(gaps[0]["blocked_concept_id"], int(target.id))
            self.assertIn("混合检索", gaps[0]["reason"])
            self.assertGreater(gaps[0]["score_components"]["prerequisite_blockage"], 0)
            self.assertGreater(gaps[0]["score_components"]["goal_relevance"], 0)

            due = next(
                item for item in result["items"]
                if item["task_type"] == "review_due" and item["concept_id"] == int(prerequisite.id)
            )
            self.assertEqual(due["fsrs_stability"], 2.5)
            self.assertGreater(due["score_components"]["urgency"], 0)
            candidate_ids = {item["concept_id"] for item in result["items"]}
            self.assertNotIn(int(pending.id), candidate_ids)
            self.assertNotIn(int(foreign.id), candidate_ids)
            self.assertIn("prerequisite_blockage", result["decision_rule"])

    async def test_event_projection_supports_explanation_application_and_hints(self):
        async with self.sessions() as session:
            concept = await upsert_concept(session, int(self.owner.id), "迁移应用")
            for event_type, score in (
                ("practice.explanation", 0.8),
                ("practice.application", 0.7),
                ("practice.hint", 0.4),
                ("study.interruption", 0.2),
            ):
                await record_learning_event(
                    session, int(self.owner.id), event_type, source="test",
                    payload={"concept_id": int(concept.id), "score": score},
                )
            await process_outbox(session, user_id=int(self.owner.id))
            evidence_types = set((
                await session.execute(
                    select(LearnerEvidence.evidence_type).where(LearnerEvidence.concept_id == int(concept.id))
                )
            ).scalars().all())
            self.assertEqual(evidence_types, {"explanation", "application", "hint_count", "interruption"})

    async def test_evidence_api_is_idempotent_and_hides_cross_user_concepts(self):
        async with self.sessions() as session:
            concept = await upsert_concept(session, int(self.owner.id), "可回放证据")
            request = LearnerEvidenceRequest(
                evidence_type="answer", score=0.9, dedupe_key="answer-attempt-001",
            )
            first = await add_concept_evidence(
                int(concept.id), request, db=session, current_user=self.owner,
            )
            second = await add_concept_evidence(
                int(concept.id), request, db=session, current_user=self.owner,
            )
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(second["state"]["attempt_count"], 1)
            with self.assertRaises(HTTPException) as denied:
                await add_concept_evidence(int(concept.id), request, db=session, current_user=self.other)
            self.assertEqual(denied.exception.status_code, 404)

            result = await learning_recommendations(
                limit=10, as_of=self.now, db=session, current_user=self.other,
            )
            self.assertEqual(result["items"], [])

    async def test_wrong_question_and_review_backfill_concept_and_learning_evidence(self):
        async with self.sessions() as session:
            created = await create_wrong_question(
                WrongQuestionCreate(
                    content="RRF 应该在 reranker 之前还是之后执行？",
                    knowledge_point="RRF",
                ),
                db=session, current_user=self.owner,
            )
            self.assertIsNotNone(created["concept_id"])
            concept_id = int(created["concept_id"])
            initial = (
                await session.execute(
                    select(LearnerEvidence).where(LearnerEvidence.concept_id == concept_id)
                )
            ).scalars().all()
            self.assertEqual([row.evidence_type for row in initial], ["answer"])

            reviewed = await review_wrong_question(
                int(created["id"]), WrongQuestionReview(quality=5, recall_difficulty="easy"),
                db=session, current_user=self.owner,
            )
            self.assertEqual(reviewed["concept_id"], concept_id)
            evidence_types = set((
                await session.execute(
                    select(LearnerEvidence.evidence_type).where(LearnerEvidence.concept_id == concept_id)
                )
            ).scalars().all())
            self.assertEqual(evidence_types, {"answer", "review_result"})

            await delete_wrong_question(int(created["id"]), db=session, current_user=self.owner)
            residue = await session.scalar(
                select(ConceptSourceEvidence.id).where(
                    ConceptSourceEvidence.source_type == "wrong_question",
                    ConceptSourceEvidence.source_id == int(created["id"]),
                )
            )
            self.assertIsNone(residue)


if __name__ == "__main__":
    unittest.main()
