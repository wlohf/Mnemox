"""Stage 2 unified extraction, grounding, idempotency, and recovery gates."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.knowledge import Claim, ClaimEvidence, KnowledgeExtractionRun, KnowledgeUnit
from app.models.material import Material
from app.models.user import User
from app.schemas.knowledge_extraction import KnowledgeExtractionResult
from app.services.knowledge_extraction_service import (
    DeterministicKnowledgeExtractor,
    LLMKnowledgeExtractor,
    cancel_extraction_run,
    claim_next_extraction_run,
    create_extraction_run,
    ground_extraction_result,
    get_material_extraction_summary,
    locate_evidence,
    process_claimed_extraction_run,
    recover_expired_extraction_runs,
    retry_extraction_run,
)
from app.services.knowledge_extraction_worker import KnowledgeExtractionWorker
from app.services.knowledge_source_service import register_material_source
from app.utils.utc import utc_now_db


def _result(statement: str, quote: str, *, local_id: str = "c1") -> KnowledgeExtractionResult:
    return KnowledgeExtractionResult.model_validate(
        {
            "claims": [
                {
                    "local_id": local_id,
                    "statement": statement,
                    "claim_kind": "observation",
                    "evidence": [{"quote": quote}],
                    "concepts": [],
                    "confidence": 0.8,
                }
            ],
            "relations": [],
        }
    )


class StaticExtractor:
    def __init__(self, result: KnowledgeExtractionResult):
        self.result = result

    async def extract(self, _unit):
        return self.result


class KnowledgeExtractionSchemaTests(unittest.IsolatedAsyncioTestCase):
    def test_schema_rejects_extra_fields_invalid_confidence_and_dangling_relations(self):
        valid = {
            "claims": [
                {
                    "local_id": "c1",
                    "statement": "A grounded statement.",
                    "claim_kind": "observation",
                    "evidence": [{"quote": "source"}],
                    "concepts": [],
                    "confidence": 0.9,
                }
            ],
            "relations": [],
        }
        with self.assertRaises(ValidationError):
            KnowledgeExtractionResult.model_validate({**valid, "provider_extension": True})
        invalid_confidence = {**valid, "claims": [{**valid["claims"][0], "confidence": 1.1}]}
        with self.assertRaises(ValidationError):
            KnowledgeExtractionResult.model_validate(invalid_confidence)
        dangling = {
            **valid,
            "relations": [
                {
                    "from_local_id": "c1",
                    "to_local_id": "missing",
                    "relation_type": "supports",
                    "confidence": 0.8,
                }
            ],
        }
        with self.assertRaises(ValidationError):
            KnowledgeExtractionResult.model_validate(dangling)

    async def test_deterministic_extractor_returns_the_shared_schema_without_network(self):
        unit = KnowledgeUnit(
            id=1,
            user_id=1,
            source_revision_id=1,
            unit_type="chunk",
            ordinal=0,
            text="机会成本：选择一个方案时放弃的最佳替代收益。\n基础概念 -> 进阶概念",
            text_hash="x" * 64,
            locator={},
        )
        result = await DeterministicKnowledgeExtractor().extract(unit)
        self.assertIsInstance(result, KnowledgeExtractionResult)
        self.assertEqual([claim.claim_kind for claim in result.claims], ["definition", "principle"])
        self.assertTrue(all(claim.evidence for claim in result.claims))

    def test_grounding_supports_exact_and_bounded_normalized_spans(self):
        exact = KnowledgeExtractionResult.model_validate(
            {
                "claims": [
                    {
                        "local_id": "c1",
                        "statement": "Unicode punctuation can be normalized.",
                        "claim_kind": "observation",
                        "evidence": [{"quote": "Ａlpha, Beta."}],
                        "concepts": [],
                        "confidence": 0.9,
                    }
                ],
                "relations": [],
            }
        )
        grounded = ground_extraction_result("Ａlpha，  Beta。", exact)
        self.assertEqual(len(grounded.claims), 1)
        evidence = grounded.claims[0].evidence[0]
        self.assertEqual(evidence.grounding_method, "normalized_span")
        self.assertEqual(evidence.excerpt, "Ａlpha，  Beta。")


class KnowledgeExtractionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'knowledge-stage2.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            user = User(
                username="stage2-owner",
                email="stage2-owner@example.test",
                hashed_password="hash",
            )
            db.add(user)
            await db.commit()
            self.user_id = int(user.id)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _revision(self, content: str) -> tuple[int, int]:
        async with self.sessions() as db:
            material = Material(
                user_id=self.user_id,
                title="Stage 2 material",
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
            db.add(material)
            await db.flush()
            revision = await register_material_source(
                db,
                user_id=self.user_id,
                material_id=int(material.id),
            )
            await db.commit()
            return int(material.id), int(revision.id)

    async def _claim_run(self, revision_id: int, *, force: bool = False) -> KnowledgeExtractionRun:
        async with self.sessions() as db:
            run = await create_extraction_run(
                db,
                user_id=self.user_id,
                source_revision_id=revision_id,
                extractor_type="deterministic",
                force=force,
            )
            await db.commit()
        async with self.sessions() as db:
            leased = await claim_next_extraction_run(db, worker_id="test-worker")
            self.assertIsNotNone(leased)
            await db.commit()
            return leased

    async def test_automatic_claims_are_pending_and_ungrounded_candidates_are_not_written(self):
        _, revision_id = await self._revision("Exact source evidence.")
        run = await self._claim_run(revision_id)
        candidate = KnowledgeExtractionResult.model_validate(
            {
                "claims": [
                    {
                        "local_id": "grounded",
                        "statement": "The source provides exact evidence.",
                        "claim_kind": "observation",
                        "evidence": [{"quote": "Exact source evidence."}],
                        "concepts": [],
                        "confidence": 0.9,
                    },
                    {
                        "local_id": "rejected",
                        "statement": "This candidate has no source location.",
                        "claim_kind": "observation",
                        "evidence": [{"quote": "invented quotation"}],
                        "concepts": [],
                        "confidence": 0.9,
                    },
                ],
                "relations": [],
            }
        )
        async with self.sessions() as db:
            finished = await process_claimed_extraction_run(
                db,
                run_id=int(run.id),
                worker_id="test-worker",
                extractor=StaticExtractor(candidate),
            )
            await db.commit()
            claims = list((await db.scalars(select(Claim))).all())
            evidence = list((await db.scalars(select(ClaimEvidence))).all())

        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].review_status, "pending")
        self.assertEqual(claims[0].derivation_type, "explicit")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(finished.stats["rejected"], 1)

    async def test_run_and_claim_writes_are_idempotent_across_force_retry(self):
        _, revision_id = await self._revision("Idempotent evidence.")
        candidate = _result("Retries do not duplicate Claims.", "Idempotent evidence.")
        first = await self._claim_run(revision_id)
        async with self.sessions() as db:
            await process_claimed_extraction_run(
                db,
                run_id=int(first.id),
                worker_id="test-worker",
                extractor=StaticExtractor(candidate),
            )
            await db.commit()

        second = await self._claim_run(revision_id, force=True)
        self.assertEqual(int(first.id), int(second.id))
        async with self.sessions() as db:
            await process_claimed_extraction_run(
                db,
                run_id=int(second.id),
                worker_id="test-worker",
                extractor=StaticExtractor(candidate),
            )
            await db.commit()
            claim_count = await db.scalar(select(func.count()).select_from(Claim))
            evidence_count = await db.scalar(select(func.count()).select_from(ClaimEvidence))
            run_count = await db.scalar(select(func.count()).select_from(KnowledgeExtractionRun))
        self.assertEqual((run_count, claim_count, evidence_count), (1, 1, 1))

    async def test_overlap_duplicate_evidence_is_merged_by_absolute_source_span(self):
        phrase = "Shared evidence sentence."
        content = "x" * 400 + phrase + "y" * 300
        with (
            patch.object(settings, "RAG_CHUNK_SIZE", 256),
            patch.object(settings, "RAG_CHUNK_OVERLAP", 64),
        ):
            _, revision_id = await self._revision(content)
        run = await self._claim_run(revision_id)

        class OverlapExtractor:
            async def extract(self, unit):
                if phrase not in unit.text:
                    return KnowledgeExtractionResult()
                return _result("Overlapping chunks describe one Claim.", phrase)

        async with self.sessions() as db:
            await process_claimed_extraction_run(
                db,
                run_id=int(run.id),
                worker_id="test-worker",
                extractor=OverlapExtractor(),
            )
            await db.commit()
            self.assertEqual(await db.scalar(select(func.count()).select_from(Claim)), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(ClaimEvidence)), 1)

    async def test_unit_failure_is_partial_and_retry_resumes_only_failed_units(self):
        content = "a" * 700
        with (
            patch.object(settings, "RAG_CHUNK_SIZE", 256),
            patch.object(settings, "RAG_CHUNK_OVERLAP", 0),
        ):
            _, revision_id = await self._revision(content)
        run = await self._claim_run(revision_id)

        class PartialExtractor:
            def __init__(self, fail_ordinal: int | None):
                self.fail_ordinal = fail_ordinal
                self.called: list[int] = []

            async def extract(self, unit):
                self.called.append(int(unit.ordinal))
                if self.fail_ordinal == int(unit.ordinal):
                    raise RuntimeError("synthetic unit failure")
                quote = str(unit.text)[:20]
                return _result(f"Unit {unit.ordinal} completed successfully.", quote)

        first_extractor = PartialExtractor(0)
        async with self.sessions() as db:
            partial = await process_claimed_extraction_run(
                db,
                run_id=int(run.id),
                worker_id="test-worker",
                extractor=first_extractor,
            )
            await db.commit()
            self.assertEqual(partial.status, "partial")
            self.assertEqual(len(partial.stats["failed_units"]), 1)

        async with self.sessions() as db:
            await retry_extraction_run(db, user_id=self.user_id, run_id=int(run.id))
            await db.commit()
        resumed = await self._claim_run(revision_id)
        retry_extractor = PartialExtractor(None)
        async with self.sessions() as db:
            finished = await process_claimed_extraction_run(
                db,
                run_id=int(resumed.id),
                worker_id="test-worker",
                extractor=retry_extractor,
            )
            await db.commit()
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(retry_extractor.called, [0])

    async def test_expired_lease_cancel_retry_and_cross_user_boundaries(self):
        _, revision_id = await self._revision("Recoverable evidence.")
        run = await self._claim_run(revision_id)
        stale_at = utc_now_db() - timedelta(seconds=300)
        async with self.sessions() as db:
            stored = await db.get(KnowledgeExtractionRun, int(run.id))
            stored.locked_at = stale_at
            await db.commit()
        async with self.sessions() as db:
            recovered = await recover_expired_extraction_runs(
                db,
                now=utc_now_db(),
                lease_seconds=30,
            )
            await db.commit()
            self.assertEqual(recovered, 1)
            stored = await db.get(KnowledgeExtractionRun, int(run.id))
            self.assertEqual(stored.status, "queued")
            cancelled = await cancel_extraction_run(
                db,
                user_id=self.user_id,
                run_id=int(run.id),
            )
            self.assertEqual(cancelled.status, "cancelled")
            await retry_extraction_run(db, user_id=self.user_id, run_id=int(run.id))
            with self.assertRaises(PermissionError):
                await cancel_extraction_run(db, user_id=self.user_id + 999, run_id=int(run.id))

    async def test_worker_processes_deterministic_run_without_an_ai_provider(self):
        _, revision_id = await self._revision("Grounding：Evidence must be exact.")
        worker = KnowledgeExtractionWorker(
            self.sessions,
            worker_id="deterministic-worker",
            batch_size=1,
            retry_base_seconds=0,
        )
        result = await worker.run_once()
        async with self.sessions() as db:
            run = await db.scalar(
                select(KnowledgeExtractionRun).where(
                    KnowledgeExtractionRun.source_revision_id == revision_id
                )
            )
            claim = await db.scalar(select(Claim))
        self.assertEqual(result, {"claimed": 1, "succeeded": 1, "partial": 0, "failed": 0})
        self.assertEqual(run.status, "succeeded")
        self.assertIsNotNone(claim)

    async def test_missing_ai_key_fails_only_llm_run_and_retains_rule_claims(self):
        with patch.object(settings, "KNOWLEDGE_LLM_EXTRACTION_ENABLED", True):
            _, revision_id = await self._revision("Grounding：Evidence must be exact.")
        worker = KnowledgeExtractionWorker(
            self.sessions,
            worker_id="no-key-worker",
            batch_size=2,
            retry_base_seconds=0,
        )
        with patch(
            "app.ai.factory.AIProviderFactory.create_provider",
            side_effect=ValueError("OpenAI API Key 未配置"),
        ):
            result = await worker.run_once()
        async with self.sessions() as db:
            runs = list(
                (
                    await db.scalars(
                        select(KnowledgeExtractionRun)
                        .where(KnowledgeExtractionRun.source_revision_id == revision_id)
                        .order_by(KnowledgeExtractionRun.id)
                    )
                ).all()
            )
            claims = list((await db.scalars(select(Claim))).all())
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(
            {run.extractor_type: run.status for run in runs},
            {"deterministic": "succeeded", "llm": "failed"},
        )
        self.assertEqual(len(claims), 1)

    async def test_material_summary_exposes_run_state_and_pending_review_count(self):
        with patch.object(settings, "KNOWLEDGE_V2_ENABLED", True):
            material_id, revision_id = await self._revision("Grounding：Evidence must be exact.")
            worker = KnowledgeExtractionWorker(
                self.sessions,
                worker_id="summary-worker",
                batch_size=1,
            )
            await worker.run_once()
            async with self.sessions() as db:
                summary = await get_material_extraction_summary(
                    db,
                    user_id=self.user_id,
                    material_id=material_id,
                )
        self.assertEqual(summary["source_revision_id"], revision_id)
        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(summary["deterministic_status"], "succeeded")
        self.assertEqual(summary["llm_status"], "disabled")
        self.assertEqual(summary["pending_claim_count"], 1)


class LLMExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_structured_output_is_preferred(self):
        class Provider:
            model = "structured-model"

            def supports_structured_output(self):
                return True

            async def chat_structured(self, **_kwargs):
                return _result("Structured output is validated.", "source quote")

            async def chat(self, **_kwargs):
                raise AssertionError("JSON fallback should not be called")

        unit = KnowledgeUnit(id=1, text="source quote", locator={})
        result = await LLMKnowledgeExtractor(Provider()).extract(unit)
        self.assertEqual(result.claims[0].local_id, "c1")

    async def test_json_fallback_is_strict(self):
        class Provider:
            def supports_structured_output(self):
                return False

            async def chat(self, **_kwargs):
                return _result("Fallback output is validated.", "source quote").model_dump_json()

        unit = KnowledgeUnit(id=1, text="source quote", locator={})
        result = await LLMKnowledgeExtractor(Provider()).extract(unit)
        self.assertEqual(result.claims[0].statement, "Fallback output is validated.")


if __name__ == "__main__":
    unittest.main()
