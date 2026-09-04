"""Stage 4 SQL graph and evidence-first association gates."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    ClaimRelation,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.user import User
from app.routers.knowledge import _require_association_v2
from app.services.association_reranker_service import (
    LlmAssociationReranker,
    UnavailableAssociationReranker,
    create_association_reranker,
)
from app.services.association_v2_service import associate
from app.services.claim_relation_service import create_claim_relation
from app.services.graph_store.sql_store import SqlGraphStore
from evaluate_knowledge import run_evaluation, run_stage4_evaluation


class DuplicateDenseIndex:
    def __init__(self, claim_id: int):
        self.claim_id = int(claim_id)

    async def query_claims(self, *, user_id: int, text: str, top_k: int):
        return [{"claim_id": self.claim_id, "score": 0.9}, {"claim_id": self.claim_id, "score": 0.8}, {"claim_id": 9999, "score": 1.0}]


class ExplodingJudge:
    async def judge(self, *, anchor, related, evidence):
        raise TimeoutError("synthetic judge timeout")


class PreferClaimReranker:
    def __init__(self, preferred_claim_id: int):
        self.preferred_claim_id = int(preferred_claim_id)

    async def score_pairs(self, *, query, candidates):
        return {
            int(row["claim_id"]): (1.0 if int(row["claim_id"]) == self.preferred_claim_id else 0.0)
            for row in candidates
        }


class SlowReranker:
    async def score_pairs(self, *, query, candidates):
        await asyncio.sleep(0.05)
        return {int(row["claim_id"]): 1.0 for row in candidates}


class FakeRerankerProvider:
    provider_name = "fake-provider"
    model = "fake-reranker-model"

    def __init__(self):
        self._usage = {}

    def supports_structured_output(self):
        return False

    def clear_last_usage(self):
        self._usage = {}

    def get_last_usage(self):
        return dict(self._usage)

    async def chat(self, messages, system_prompt=None, temperature=0.0):
        self._usage = {
            "provider": self.provider_name,
            "model": self.model,
            "input_tokens": 20,
            "output_tokens": 8,
            "total_tokens": 28,
            "configured_cost_usd": 0.00001,
        }
        return '{"scores":[{"claim_id":1,"score":0.25},{"claim_id":2,"score":0.95}]}'


class AssociationV2Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'stage4.db'}")
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        user = User(username=name, email=f"{name}@example.test", hashed_password="hash")
        db.add(user)
        await db.flush()
        return user

    async def _claim(self, db, *, user_id: int, record_id: int, statement: str, status: str = "active", revision_status: str = "current", source_status: str = "active", evidence: bool = True):
        source = KnowledgeSource(user_id=user_id, source_type="note", source_record_id=record_id, source_key=f"note:{record_id}", title_snapshot=f"Source {record_id}", status=source_status, current_revision=1)
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(user_id=user_id, knowledge_source_id=int(source.id), revision=1, content_hash=hashlib.sha256(statement.encode()).hexdigest(), title_snapshot=source.title_snapshot, status=revision_status)
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(user_id=user_id, source_revision_id=int(revision.id), unit_type="note_body", ordinal=0, text=statement, text_hash=hashlib.sha256(statement.encode()).hexdigest(), locator={})
        claim = Claim(user_id=user_id, source_revision_id=int(revision.id), statement=statement, fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(), confidence=0.9, derivation_type="manual", review_status="confirmed", lifecycle_status=status)
        db.add_all((unit, claim))
        await db.flush()
        if evidence:
            db.add(ClaimEvidence(user_id=user_id, claim_id=int(claim.id), knowledge_unit_id=int(unit.id), excerpt=statement, char_start=0, char_end=len(statement), locator={}, grounding_method="manual", confidence=0.9))
            await db.flush()
        return source, claim

    async def test_graph_store_isolates_users_and_filters_noncurrent_or_deleted_claims(self):
        async with self.sessions() as db:
            owner = await self._user(db, "graph-owner")
            stranger = await self._user(db, "graph-stranger")
            concept = Concept(user_id=int(owner.id), name="Tradeoff", name_normalized="tradeoff", source="manual", review_status="confirmed")
            db.add(concept)
            await db.flush()
            _, anchor = await self._claim(db, user_id=int(owner.id), record_id=1, statement="Anchor tradeoff")
            _, visible = await self._claim(db, user_id=int(owner.id), record_id=2, statement="Visible tradeoff")
            _, deleted = await self._claim(db, user_id=int(owner.id), record_id=3, statement="Deleted tradeoff", status="deleted")
            _, superseded = await self._claim(db, user_id=int(owner.id), record_id=4, statement="Old tradeoff", revision_status="superseded")
            _, foreign = await self._claim(db, user_id=int(stranger.id), record_id=5, statement="Private tradeoff")
            for claim in (anchor, visible, deleted, superseded):
                db.add(ClaimConceptLink(user_id=int(owner.id), claim_id=int(claim.id), concept_id=int(concept.id), relation_type="about", mention_text="tradeoff", confidence=1.0, derivation_type="manual", review_status="confirmed"))
            # A malformed cross-tenant edge cannot make the foreign Claim visible.
            db.add(ClaimRelation(user_id=int(owner.id), from_claim_id=int(anchor.id), to_claim_id=int(foreign.id), relation_type="supports", confidence=1.0, derivation_type="manual", review_status="confirmed", rationale="must be filtered"))
            await db.commit()
            hits = await SqlGraphStore(db).expand_claims(user_id=int(owner.id), claim_ids=(int(anchor.id),), patterns=("shared_concept_claims", "direct_claim_relations"), depth=2, limit=20)
            self.assertEqual({row.object_id for row in hits}, {int(visible.id)})

    async def test_relation_mutation_enforces_ownership_lifecycle_and_flush_only(self):
        async with self.sessions() as db:
            owner = await self._user(db, "relation-owner")
            stranger = await self._user(db, "relation-stranger")
            _, left = await self._claim(db, user_id=int(owner.id), record_id=11, statement="Left evidence")
            _, right = await self._claim(db, user_id=int(owner.id), record_id=12, statement="Right evidence")
            _, foreign = await self._claim(db, user_id=int(stranger.id), record_id=13, statement="Foreign evidence")
            _, stale = await self._claim(
                db,
                user_id=int(owner.id),
                record_id=14,
                statement="Stale evidence",
                revision_status="superseded",
            )
            _, deleted_source = await self._claim(
                db,
                user_id=int(owner.id),
                record_id=15,
                statement="Deleted source evidence",
                source_status="deleted",
            )
            row = await create_claim_relation(db, user_id=int(owner.id), from_claim_id=int(right.id), to_claim_id=int(left.id), relation_type="analogous_to", confidence=0.8, rationale="Grounded analogy", evidence_provenance={"claim_evidence_ids": [1, 2]})
            self.assertEqual((row.from_claim_id, row.to_claim_id), tuple(sorted((left.id, right.id))))
            self.assertTrue(db.in_transaction())
            for invalid_claim in (foreign, stale, deleted_source):
                with self.assertRaises(PermissionError):
                    await create_claim_relation(db, user_id=int(owner.id), from_claim_id=int(left.id), to_claim_id=int(invalid_claim.id), relation_type="supports", confidence=1.0)

    async def test_source_context_excludes_same_source_claims(self):
        async with self.sessions() as db:
            owner = await self._user(db, "source-context-owner")
            source, anchor = await self._claim(db, user_id=int(owner.id), record_id=16, statement="Anchor source text")
            same_source = Claim(
                user_id=int(owner.id),
                source_revision_id=int(anchor.source_revision_id),
                statement="Same source related text",
                fingerprint=hashlib.sha256(b"same-source-related-text").hexdigest(),
                confidence=0.9,
                derivation_type="manual",
                review_status="confirmed",
                lifecycle_status="active",
            )
            db.add(same_source)
            await db.flush()
            unit = await db.scalar(select(KnowledgeUnit).where(KnowledgeUnit.source_revision_id == int(anchor.source_revision_id)))
            db.add(ClaimEvidence(user_id=int(owner.id), claim_id=int(same_source.id), knowledge_unit_id=int(unit.id), excerpt="Same source related text", char_start=0, char_end=len("Same source related text"), locator={}, grounding_method="manual", confidence=0.9))
            await db.commit()
            payload = await associate(
                db,
                user_id=int(owner.id),
                text="related text",
                source_type="note",
                source_id=int(source.source_record_id),
                dense_index=DuplicateDenseIndex(int(same_source.id)),
                limit=5,
            )
            self.assertEqual(payload["associations"], [])

    async def test_no_evidence_never_displays_and_ranking_dedup_is_deterministic(self):
        async with self.sessions() as db:
            owner = await self._user(db, "association-owner")
            _, first = await self._claim(db, user_id=int(owner.id), record_id=21, statement="Memory practice retrieves an answer")
            _, no_evidence = await self._claim(db, user_id=int(owner.id), record_id=22, statement="Memory practice unsupported", evidence=False)
            await db.commit()
            dense = DuplicateDenseIndex(int(first.id))
            first_result = await associate(db, user_id=int(owner.id), text="memory practice retrieves answer", dense_index=dense, limit=5)
            second_result = await associate(db, user_id=int(owner.id), text="memory practice retrieves answer", dense_index=dense, limit=5)
            self.assertEqual(first_result, second_result)
            self.assertEqual(len(first_result["associations"]), 1)
            self.assertEqual(first_result["associations"][0]["related"]["claim_id"], int(first.id))
            self.assertNotEqual(first_result["associations"][0]["related"]["claim_id"], int(no_evidence.id))
            self.assertTrue(first_result["associations"][0]["evidence"]["related"])

    async def test_multihop_explanation_flag_only_enriches_and_does_not_change_ranking(self):
        async with self.sessions() as db:
            owner = await self._user(db, "explanation-flag-owner")
            _, first = await self._claim(db, user_id=int(owner.id), record_id=23, statement="Memory practice retrieves an answer")
            _, second = await self._claim(db, user_id=int(owner.id), record_id=24, statement="Memory practice recalls an answer")
            await db.commit()
            dense = DuplicateDenseIndex(int(first.id))
            explanation = {
                "kind": "graph_path",
                "summary": "共同关联到「Memory Practice」",
                "steps": [
                    {"type": "anchor", "label": "当前内容"},
                    {"type": "concept", "name": "Memory Practice"},
                    {"type": "related_claim", "label": "候选知识"},
                ],
                "evidence": [],
            }
            with patch(
                "app.services.association_explanation_service.build_association_explanation",
                return_value=explanation,
            ) as builder:
                with patch.object(settings, "ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED", False):
                    disabled = await associate(
                        db,
                        user_id=int(owner.id),
                        text="memory practice answer",
                        dense_index=dense,
                        limit=5,
                    )
                self.assertEqual(builder.call_count, 0)
                with patch.object(settings, "ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED", True):
                    enabled = await associate(
                        db,
                        user_id=int(owner.id),
                        text="memory practice answer",
                        dense_index=dense,
                        limit=5,
                    )

            disabled_order = [row["related"]["claim_id"] for row in disabled["associations"]]
            enabled_order = [row["related"]["claim_id"] for row in enabled["associations"]]
            self.assertEqual(disabled_order, enabled_order)
            self.assertEqual(
                [row["score"] for row in disabled["associations"]],
                [row["score"] for row in enabled["associations"]],
            )
            self.assertGreaterEqual(builder.call_count, 1)
            self.assertEqual(enabled["associations"][0]["explanation"], explanation)
            self.assertNotIn("explanation", disabled["associations"][0])
            self.assertIn(int(first.id), enabled_order)
            self.assertIn(int(second.id), enabled_order)

    async def test_llm_reranker_records_model_latency_and_usage(self):
        reranker = LlmAssociationReranker(FakeRerankerProvider())
        scores = await reranker.score_pairs(
            query="memory practice",
            candidates=[
                {"claim_id": 1, "claim": "first", "source_type": "note"},
                {"claim_id": 2, "claim": "second", "source_type": "note"},
            ],
        )
        self.assertEqual(scores, {1: 0.25, 2: 0.95})
        self.assertEqual(reranker.last_diagnostics["provider"], "fake-provider")
        self.assertEqual(reranker.last_diagnostics["model"], "fake-reranker-model")
        self.assertGreaterEqual(reranker.last_diagnostics["latency_ms"], 0.0)
        self.assertEqual(reranker.last_diagnostics["usage"]["total_tokens"], 28)

    async def test_llm_reranker_provider_failure_returns_fallback_adapter(self):
        with patch.object(settings, "KNOWLEDGE_RERANKER_MODE", "llm"), patch(
            "app.services.association_reranker_service.AIProviderFactory.create_provider",
            side_effect=ValueError("provider missing"),
        ):
            reranker = await create_association_reranker(db=None, user_id=1)
        self.assertIsInstance(reranker, UnavailableAssociationReranker)
        with self.assertRaises(RuntimeError):
            await reranker.score_pairs(query="x", candidates=[{"claim_id": 1}])

    async def test_semantic_reranker_can_reorder_candidates_without_bypassing_evidence(self):
        async with self.sessions() as db:
            owner = await self._user(db, "reranker-owner")
            _, first = await self._claim(db, user_id=int(owner.id), record_id=25, statement="Memory practice retrieves an answer from memory")
            _, second = await self._claim(db, user_id=int(owner.id), record_id=26, statement="Memory practice recalls an answer from memory")
            await db.commit()
            result = await associate(
                db,
                user_id=int(owner.id),
                text="memory practice answer",
                semantic_reranker=PreferClaimReranker(int(second.id)),
                limit=5,
            )
            self.assertEqual(result["diagnostics"]["reranker"], "semantic")
            self.assertEqual(result["associations"][0]["related"]["claim_id"], int(second.id))
            self.assertTrue(result["associations"][0]["evidence"]["related"])

    async def test_semantic_reranker_timeout_keeps_feature_ranker_results(self):
        async with self.sessions() as db:
            owner = await self._user(db, "reranker-timeout-owner")
            _, claim = await self._claim(db, user_id=int(owner.id), record_id=27, statement="Feedback loop changes the next input")
            await db.commit()
            with patch.object(settings, "KNOWLEDGE_RERANKER_TIMEOUT_SECONDS", 0.001):
                result = await associate(
                    db,
                    user_id=int(owner.id),
                    text="feedback loop next input",
                    semantic_reranker=SlowReranker(),
                    limit=5,
                )
            self.assertEqual(result["diagnostics"]["reranker"], "feature")
            self.assertEqual(result["diagnostics"]["degraded_sources"].get("reranker"), "feature_fallback")
            self.assertEqual(result["associations"][0]["related"]["claim_id"], int(claim.id))

    async def test_judge_failure_falls_back_to_confirmed_graph_result(self):
        async with self.sessions() as db:
            owner = await self._user(db, "judge-owner")
            concept = Concept(user_id=int(owner.id), name="Feedback Loop", name_normalized="feedback loop", source="manual", review_status="confirmed")
            db.add(concept)
            await db.flush()
            anchor_source, anchor = await self._claim(db, user_id=int(owner.id), record_id=31, statement="Output changes the next input")
            _, related = await self._claim(db, user_id=int(owner.id), record_id=32, statement="A system output feeds back into later input")
            for claim in (anchor, related):
                db.add(ClaimConceptLink(user_id=int(owner.id), claim_id=int(claim.id), concept_id=int(concept.id), relation_type="about", mention_text="feedback loop", confidence=1.0, derivation_type="manual", review_status="confirmed"))
            await db.commit()
            result = await associate(
                db,
                user_id=int(owner.id),
                text="feedback loop",
                source_type="note",
                source_id=int(anchor_source.source_record_id),
                judge=ExplodingJudge(),
                limit=5,
            )
            self.assertEqual(len(result["associations"]), 1)
            self.assertEqual(result["associations"][0]["related"]["claim_id"], int(related.id))
            self.assertEqual(result["diagnostics"]["degraded_sources"].get("judge"), "fallback_confirmed_paths_only")

    def test_api_requires_both_flags_without_changing_v1_switch(self):
        with patch.object(settings, "KNOWLEDGE_V2_ENABLED", False), patch.object(settings, "ASSOCIATION_V2_ENABLED", True):
            with self.assertRaises(HTTPException):
                _require_association_v2()
        with patch.object(settings, "KNOWLEDGE_V2_ENABLED", True), patch.object(settings, "ASSOCIATION_V2_ENABLED", False):
            with self.assertRaises(HTTPException):
                _require_association_v2()
        with patch.object(settings, "KNOWLEDGE_V2_ENABLED", True), patch.object(settings, "ASSOCIATION_V2_ENABLED", True):
            _require_association_v2()


class AssociationV2EvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_stage4_improves_implicit_recall_without_regressing_explicit(self):
        v1 = await run_evaluation()
        v2_first = await run_stage4_evaluation()
        v2_second = await run_stage4_evaluation()
        self.assertGreaterEqual(v2_first["results"]["explicit"]["recall_at_5"], v1["results"]["explicit"]["recall_at_5"])
        self.assertGreaterEqual(v2_first["results"]["implicit"]["recall_at_5"] - v1["results"]["implicit"]["recall_at_5"], 0.20)
        self.assertEqual(v2_first["deterministic_result_sha256"], v2_second["deterministic_result_sha256"])
        self.assertEqual(v2_first["external_model_calls"], 0)
        self.assertEqual(v2_first["lifecycle_probes"], {"user_isolation_violations": 0, "deleted_source_residual_hits": 0, "unsupported_display_count": 0, "negative_false_positive_count": 0})
