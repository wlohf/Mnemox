"""Stage 3 conservative entity-resolution and user-review gates."""
from __future__ import annotations

import hashlib
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept, ConceptAlias
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    EntityResolutionCandidate,
    KnowledgeExtractionRun,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.user import User
from app.schemas.knowledge_extraction import ExtractedConceptMention
from app.services.entity_resolution_service import (
    list_resolution_candidates,
    resolve_candidate,
    resolve_claim_mentions,
)
from evaluate_entity_resolution import run_resolution_evaluation


class StaticConceptIndex:
    def __init__(self, rows: list[dict[str, float | int]]):
        self.rows = rows
        self.queries: list[tuple[int, str, int]] = []

    async def query_concepts(self, *, user_id: int, text: str, top_k: int):
        self.queries.append((int(user_id), str(text), int(top_k)))
        return self.rows[:top_k]


class TimeoutConceptIndex:
    async def query_concepts(self, *, user_id: int, text: str, top_k: int):
        raise asyncio.TimeoutError("synthetic embedding timeout")


class EntityResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'entity-resolution.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.next_source_id = 1

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        row = User(username=name, email=f"{name}@example.test", hashed_password="hash")
        db.add(row)
        await db.flush()
        return row

    async def _concept(self, db, user_id: int, name: str) -> Concept:
        row = Concept(
            user_id=int(user_id),
            name=name,
            name_normalized=name.casefold(),
            source="manual",
            review_status="confirmed",
        )
        db.add(row)
        await db.flush()
        return row

    async def _context(self, db, user_id: int, statement: str = "Grounded claim"):
        source_number = self.next_source_id
        self.next_source_id += 1
        source = KnowledgeSource(
            user_id=int(user_id),
            source_type="material",
            source_record_id=source_number,
            source_key=f"material:{source_number}",
            title_snapshot=f"Source {source_number}",
            status="active",
            current_revision=1,
        )
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=int(user_id),
            knowledge_source_id=int(source.id),
            revision=1,
            content_hash=hashlib.sha256(statement.encode()).hexdigest(),
            title_snapshot=source.title_snapshot,
            status="current",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=int(user_id),
            source_revision_id=int(revision.id),
            unit_type="chunk",
            ordinal=0,
            text=f"Evidence for {statement}.",
            text_hash=hashlib.sha256(statement.encode()).hexdigest(),
            locator={"char_start": 0},
        )
        run = KnowledgeExtractionRun(
            user_id=int(user_id),
            source_revision_id=int(revision.id),
            extractor_type="deterministic",
            extractor_version="test-v1",
            schema_version=1,
            input_hash=hashlib.sha256(f"run:{statement}".encode()).hexdigest(),
            status="succeeded",
        )
        claim = Claim(
            user_id=int(user_id),
            source_revision_id=int(revision.id),
            statement=statement,
            fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(),
            claim_kind="observation",
            confidence=0.8,
            derivation_type="explicit",
            review_status="pending",
            lifecycle_status="active",
            schema_version=1,
        )
        db.add_all((unit, run, claim))
        await db.flush()
        return source, revision, unit, run, claim

    async def test_canonical_and_alias_exact_matches_are_confirmed_at_one_hundred_percent(self):
        async with self.sessions() as db:
            owner = await self._user(db, "exact-owner")
            canonical = await self._concept(db, int(owner.id), "机会成本")
            alias_target = await self._concept(db, int(owner.id), "梯度下降")
            db.add(
                ConceptAlias(
                    user_id=int(owner.id),
                    concept_id=int(alias_target.id),
                    alias="gradient descent",
                    alias_normalized="gradient descent",
                    source="manual",
                )
            )
            _, _, unit, run, claim = await self._context(db, int(owner.id))
            stats = await resolve_claim_mentions(
                db,
                run=run,
                unit=unit,
                claim=claim,
                mentions=(
                    ExtractedConceptMention(text="机会成本"),
                    ExtractedConceptMention(text="Gradient Descent", relation_type="uses"),
                ),
            )
            await db.commit()
            candidates = list((await db.scalars(select(EntityResolutionCandidate))).all())
            links = list((await db.scalars(select(ClaimConceptLink))).all())

        self.assertEqual(
            stats,
            {"mentions": 2, "exact": 1, "alias": 1, "reused": 0, "pending": 0},
        )
        self.assertEqual({row.decision for row in candidates}, {"accepted"})
        self.assertEqual({float(row.combined_score) for row in candidates}, {1.0})
        self.assertEqual(
            {row.derivation_type for row in links},
            {"canonical_exact", "alias_exact"},
        )
        self.assertEqual({row.review_status for row in links}, {"confirmed"})
        self.assertEqual({row.concept_id for row in links}, {canonical.id, alias_target.id})

    async def test_semantic_top_k_is_review_only_and_filters_cross_user_ids(self):
        async with self.sessions() as db:
            owner = await self._user(db, "semantic-owner")
            stranger = await self._user(db, "semantic-stranger")
            owned = await self._concept(db, int(owner.id), "边际收益")
            forbidden = await self._concept(db, int(stranger.id), "Private concept")
            _, _, unit, run, claim = await self._context(db, int(owner.id), "Trade-off evidence")
            before = int(await db.scalar(select(func.count(Concept.id))) or 0)
            index = StaticConceptIndex(
                [
                    {"concept_id": int(forbidden.id), "score": 0.99},
                    {"concept_id": int(owned.id), "score": 0.92},
                ]
            )
            with patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", True):
                stats = await resolve_claim_mentions(
                    db,
                    run=run,
                    unit=unit,
                    claim=claim,
                    mentions=(ExtractedConceptMention(text="incremental payoff"),),
                    embedding_index=index,
                )
            await db.commit()
            candidates = list((await db.scalars(select(EntityResolutionCandidate))).all())
            links = list((await db.scalars(select(ClaimConceptLink))).all())
            after = int(await db.scalar(select(func.count(Concept.id))) or 0)

        self.assertEqual(stats["pending"], 1)
        self.assertEqual([row.candidate_concept_id for row in candidates], [owned.id])
        self.assertEqual([row.decision for row in candidates], ["pending"])
        self.assertEqual(links, [])
        self.assertEqual(before, after)
        self.assertEqual(index.queries[0][0], owner.id)

    async def test_user_can_link_add_alias_create_or_reject_without_cross_user_access(self):
        async with self.sessions() as db:
            owner = await self._user(db, "review-owner")
            stranger = await self._user(db, "review-stranger")
            target = await self._concept(db, int(owner.id), "Canonical target")
            _, _, unit, run, claim = await self._context(db, int(owner.id), "Review evidence")
            with (
                patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
                patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", False),
                patch.object(settings, "KNOWLEDGE_RESOLUTION_LEXICAL_THRESHOLD", 1.0),
            ):
                await resolve_claim_mentions(
                    db,
                    run=run,
                    unit=unit,
                    claim=claim,
                    mentions=(
                        ExtractedConceptMention(text="Brand wording"),
                        ExtractedConceptMention(text="Novel concept", relation_type="uses"),
                        ExtractedConceptMention(text="Noise", relation_type="exemplifies"),
                    ),
                )
                rows = list(
                    (
                        await db.scalars(
                            select(EntityResolutionCandidate).order_by(EntityResolutionCandidate.id)
                        )
                    ).all()
                )
                by_mention = {row.mention_text: row for row in rows}
                with self.assertRaises(PermissionError):
                    await resolve_candidate(
                        db,
                        user_id=int(stranger.id),
                        candidate_id=int(rows[0].id),
                        action="reject",
                    )
                linked = await resolve_candidate(
                    db,
                    user_id=int(owner.id),
                    candidate_id=int(by_mention["Brand wording"].id),
                    action="link_add_alias",
                    concept_id=int(target.id),
                )
                created = await resolve_candidate(
                    db,
                    user_id=int(owner.id),
                    candidate_id=int(by_mention["Novel concept"].id),
                    action="create_new",
                )
                rejected = await resolve_candidate(
                    db,
                    user_id=int(owner.id),
                    candidate_id=int(by_mention["Noise"].id),
                    action="reject",
                )
                visible = await list_resolution_candidates(
                    db,
                    user_id=int(owner.id),
                    decision="all",
                )
            await db.commit()
            alias = await db.scalar(
                select(ConceptAlias).where(
                    ConceptAlias.user_id == int(owner.id),
                    ConceptAlias.alias_normalized == "brand wording",
                )
            )
            links = list(
                (
                    await db.scalars(
                        select(ClaimConceptLink).where(ClaimConceptLink.user_id == int(owner.id))
                    )
                ).all()
            )

        self.assertEqual(linked["decision"], "accepted")
        self.assertEqual(created["decision"], "create_new")
        self.assertEqual(rejected["decision"], "rejected")
        self.assertIsNotNone(alias)
        self.assertEqual(len(links), 2)
        self.assertEqual(len(visible), 3)
        self.assertTrue(all(row["source_title"] == "Source 1" for row in visible))

    async def test_cross_user_only_vector_hits_fall_back_to_create_new_review_candidate(self):
        async with self.sessions() as db:
            owner = await self._user(db, "fallback-owner")
            stranger = await self._user(db, "fallback-stranger")
            forbidden = await self._concept(db, int(stranger.id), "Foreign only")
            _, _, unit, run, claim = await self._context(db, int(owner.id), "Fallback evidence")
            with patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", True):
                await resolve_claim_mentions(
                    db,
                    run=run,
                    unit=unit,
                    claim=claim,
                    mentions=(ExtractedConceptMention(text="unknown phrase"),),
                    embedding_index=StaticConceptIndex(
                        [{"concept_id": int(forbidden.id), "score": 1.0}]
                    ),
                )
            row = await db.scalar(select(EntityResolutionCandidate))

        self.assertIsNotNone(row)
        self.assertIsNone(row.candidate_concept_id)
        self.assertEqual(row.decision, "pending")

    async def test_embedding_timeout_keeps_exact_resolution_and_review_fallback_available(self):
        async with self.sessions() as db:
            owner = await self._user(db, "timeout-owner")
            concept = await self._concept(db, int(owner.id), "Stable exact concept")
            _, _, unit, run, claim = await self._context(db, int(owner.id), "Timeout evidence")
            with patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", True):
                stats = await resolve_claim_mentions(
                    db,
                    run=run,
                    unit=unit,
                    claim=claim,
                    mentions=(
                        ExtractedConceptMention(text="Stable exact concept"),
                        ExtractedConceptMention(text="Unresolved after timeout", relation_type="uses"),
                    ),
                    embedding_index=TimeoutConceptIndex(),
                )
            rows = list(
                (
                    await db.scalars(
                        select(EntityResolutionCandidate).order_by(EntityResolutionCandidate.id)
                    )
                ).all()
            )

        self.assertEqual(
            stats,
            {"mentions": 2, "exact": 1, "alias": 0, "reused": 0, "pending": 1},
        )
        self.assertEqual(rows[0].resolved_concept_id, concept.id)
        self.assertEqual(rows[0].decision, "accepted")
        self.assertIsNone(rows[1].candidate_concept_id)
        self.assertEqual(rows[1].decision, "pending")

    async def test_same_source_user_mapping_is_reused_without_creating_an_alias(self):
        async with self.sessions() as db:
            owner = await self._user(db, "reuse-owner")
            target = await self._concept(db, int(owner.id), "Canonical reuse target")
            _, revision, unit, run, first_claim = await self._context(
                db,
                int(owner.id),
                "First claim",
            )
            with patch.object(settings, "KNOWLEDGE_RESOLUTION_LEXICAL_THRESHOLD", 1.0):
                await resolve_claim_mentions(
                    db,
                    run=run,
                    unit=unit,
                    claim=first_claim,
                    mentions=(ExtractedConceptMention(text="Local shorthand"),),
                )
                first_candidate = await db.scalar(select(EntityResolutionCandidate))
                await resolve_candidate(
                    db,
                    user_id=int(owner.id),
                    candidate_id=int(first_candidate.id),
                    action="link",
                    concept_id=int(target.id),
                )
                second_claim = Claim(
                    user_id=int(owner.id),
                    source_revision_id=int(revision.id),
                    statement="Second claim",
                    fingerprint=hashlib.sha256(b"second claim").hexdigest(),
                    claim_kind="observation",
                    confidence=0.8,
                    derivation_type="explicit",
                    review_status="pending",
                    lifecycle_status="active",
                    schema_version=1,
                )
                db.add(second_claim)
                await db.flush()
                stats = await resolve_claim_mentions(
                    db,
                    run=run,
                    unit=unit,
                    claim=second_claim,
                    mentions=(ExtractedConceptMention(text="Local shorthand"),),
                )
            aliases = list((await db.scalars(select(ConceptAlias))).all())
            second_link = await db.scalar(
                select(ClaimConceptLink).where(ClaimConceptLink.claim_id == int(second_claim.id))
            )

        self.assertEqual(stats["reused"], 1)
        self.assertEqual(aliases, [])
        self.assertEqual(second_link.concept_id, target.id)
        self.assertEqual(second_link.derivation_type, "user")
        self.assertEqual(second_link.review_status, "confirmed")


class EntityResolutionEvaluationTests(unittest.TestCase):
    def test_recorded_stage0_semantic_rankings_clear_the_stage3_top5_gate(self):
        first = run_resolution_evaluation()
        second = run_resolution_evaluation()

        self.assertEqual(first["positive_cases"], 24)
        self.assertEqual(first["negative_cases"], 4)
        self.assertGreaterEqual(
            first["semantic_top5_recall"],
            first["semantic_top5_threshold"],
        )
        self.assertEqual(first["negative_accuracy"], 1.0)
        self.assertEqual(first["cross_user_hits"], 0)
        self.assertEqual(first["automatic_semantic_merges"], 0)
        self.assertEqual(first["external_model_calls"], 0)
        self.assertEqual(
            first["deterministic_result_sha256"],
            second["deterministic_result_sha256"],
        )
