"""Post-Stage-7 Knowledge Lab backend contract tests."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.material import Material
from app.models.user import User
from app.routers.knowledge import ClaimReviewRequest, review_knowledge_claim
from app.services.knowledge_lab_service import material_claim_snapshot


class KnowledgeLabTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'knowledge-lab.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        row = User(
            username=name,
            email=f"{name}@example.test",
            hashed_password="hash",
        )
        db.add(row)
        await db.flush()
        return row

    async def _material_graph(self, db, *, user_id: int, title: str = "Agent Notes"):
        body = "Tool Calling lets an agent invoke tools. Agent Runtime manages the loop."
        material = Material(
            user_id=int(user_id),
            title=title,
            file_type="md",
            file_path=f"/tmp/{title}.md",
            file_hash=hashlib.sha256(title.encode()).hexdigest(),
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
            content=body,
            content_status="extracted",
        )
        db.add(material)
        await db.flush()
        source = KnowledgeSource(
            user_id=int(user_id),
            source_type="material",
            source_record_id=int(material.id),
            source_key=f"material:{int(material.id)}",
            title_snapshot=title,
            status="active",
            current_revision=1,
        )
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=int(user_id),
            knowledge_source_id=int(source.id),
            revision=1,
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
            title_snapshot=title,
            status="current",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=int(user_id),
            source_revision_id=int(revision.id),
            unit_type="chunk",
            ordinal=0,
            text=body,
            text_hash=hashlib.sha256(body.encode()).hexdigest(),
            locator={"chunk": 0},
        )
        db.add(unit)
        await db.flush()
        return material, source, revision, unit

    async def _claim(
        self,
        db,
        *,
        user_id: int,
        revision_id: int,
        unit: KnowledgeUnit,
        statement: str,
        review_status: str = "pending",
        evidence: bool = True,
    ) -> Claim:
        claim = Claim(
            user_id=int(user_id),
            source_revision_id=int(revision_id),
            statement=statement,
            claim_kind="principle",
            fingerprint=hashlib.sha256(statement.encode()).hexdigest(),
            confidence=0.91,
            derivation_type="explicit",
            review_status=review_status,
            lifecycle_status="active",
            schema_version=1,
        )
        db.add(claim)
        await db.flush()
        if evidence:
            excerpt = statement if statement in unit.text else unit.text[:32]
            start = unit.text.find(excerpt)
            if start < 0:
                start = 0
                excerpt = unit.text[:32]
            db.add(
                ClaimEvidence(
                    user_id=int(user_id),
                    claim_id=int(claim.id),
                    knowledge_unit_id=int(unit.id),
                    excerpt=excerpt,
                    char_start=start,
                    char_end=start + len(excerpt),
                    locator={"chunk": 0},
                    grounding_method="exact_span",
                    confidence=0.95,
                )
            )
        await db.flush()
        return claim

    async def test_snapshot_rehydrates_current_claim_evidence_and_concepts(self):
        async with self.sessions() as db:
            owner = await self._user(db, "lab-owner")
            material, _source, revision, unit = await self._material_graph(db, user_id=owner.id)
            pending = await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Tool Calling lets an agent invoke tools.",
                review_status="pending",
            )
            confirmed = await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Agent Runtime manages the loop.",
                review_status="confirmed",
            )
            concept = Concept(
                user_id=int(owner.id),
                name="Tool Calling",
                name_normalized="tool calling",
                source="manual",
                review_status="confirmed",
            )
            db.add(concept)
            await db.flush()
            db.add(
                ClaimConceptLink(
                    user_id=int(owner.id),
                    claim_id=int(pending.id),
                    concept_id=int(concept.id),
                    relation_type="about",
                    mention_text="Tool Calling",
                    confidence=0.99,
                    derivation_type="manual",
                    review_status="confirmed",
                )
            )
            await db.commit()

            snapshot = await material_claim_snapshot(
                db,
                user_id=int(owner.id),
                material_id=int(material.id),
            )

            self.assertTrue(snapshot["source"]["registered"])
            self.assertEqual(snapshot["counts"]["total"], 2)
            self.assertEqual(snapshot["counts"]["pending"], 1)
            self.assertEqual(snapshot["counts"]["confirmed"], 1)
            self.assertEqual([row["id"] for row in snapshot["claims"]], [int(pending.id), int(confirmed.id)])
            first = snapshot["claims"][0]
            self.assertEqual(first["evidence"][0]["excerpt"], "Tool Calling lets an agent invoke tools.")
            self.assertEqual(first["concepts"][0]["name"], "Tool Calling")
            self.assertNotIn("text", first["evidence"][0]["unit"])

    async def test_snapshot_filter_and_cross_user_material_isolation(self):
        async with self.sessions() as db:
            owner = await self._user(db, "lab-filter-owner")
            stranger = await self._user(db, "lab-filter-stranger")
            material, _source, revision, unit = await self._material_graph(db, user_id=owner.id)
            foreign_material, *_ = await self._material_graph(db, user_id=stranger.id, title="Private Notes")
            await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Tool Calling lets an agent invoke tools.",
                review_status="pending",
            )
            await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Agent Runtime manages the loop.",
                review_status="confirmed",
            )
            await db.commit()

            confirmed = await material_claim_snapshot(
                db,
                user_id=int(owner.id),
                material_id=int(material.id),
                review_status="confirmed",
            )
            self.assertEqual(len(confirmed["claims"]), 1)
            self.assertEqual(confirmed["claims"][0]["review_status"], "confirmed")
            with self.assertRaises(PermissionError):
                await material_claim_snapshot(
                    db,
                    user_id=int(owner.id),
                    material_id=int(foreign_material.id),
                )

    async def test_claim_review_endpoint_confirms_grounded_claim_and_rejects_claim(self):
        async with self.sessions() as db:
            owner = await self._user(db, "lab-review-owner")
            _material, _source, revision, unit = await self._material_graph(db, user_id=owner.id)
            confirm_me = await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Tool Calling lets an agent invoke tools.",
                review_status="pending",
            )
            reject_me = await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Agent Runtime manages the loop.",
                review_status="pending",
            )
            await db.commit()

            with patch.object(settings, "KNOWLEDGE_V2_ENABLED", True):
                confirmed = await review_knowledge_claim(
                    claim_id=int(confirm_me.id),
                    body=ClaimReviewRequest(review_status="confirmed"),
                    db=db,
                    current_user=owner,
                )
                rejected = await review_knowledge_claim(
                    claim_id=int(reject_me.id),
                    body=ClaimReviewRequest(review_status="rejected"),
                    db=db,
                    current_user=owner,
                )
            self.assertEqual(confirmed["review_status"], "confirmed")
            self.assertEqual(rejected["review_status"], "rejected")

    async def test_claim_review_requires_evidence_and_hides_foreign_claim(self):
        async with self.sessions() as db:
            owner = await self._user(db, "lab-review-evidence-owner")
            stranger = await self._user(db, "lab-review-evidence-stranger")
            _material, _source, revision, unit = await self._material_graph(db, user_id=owner.id)
            no_evidence = await self._claim(
                db,
                user_id=owner.id,
                revision_id=revision.id,
                unit=unit,
                statement="Ungrounded extracted statement",
                review_status="pending",
                evidence=False,
            )
            _foreign_material, _foreign_source, foreign_revision, foreign_unit = await self._material_graph(
                db,
                user_id=stranger.id,
                title="Foreign Review Notes",
            )
            foreign_claim = await self._claim(
                db,
                user_id=stranger.id,
                revision_id=foreign_revision.id,
                unit=foreign_unit,
                statement="Private grounded statement",
                review_status="pending",
            )
            await db.commit()

            with patch.object(settings, "KNOWLEDGE_V2_ENABLED", True):
                with self.assertRaises(HTTPException) as no_evidence_ctx:
                    await review_knowledge_claim(
                        claim_id=int(no_evidence.id),
                        body=ClaimReviewRequest(review_status="confirmed"),
                        db=db,
                        current_user=owner,
                    )
                with self.assertRaises(HTTPException) as foreign_ctx:
                    await review_knowledge_claim(
                        claim_id=int(foreign_claim.id),
                        body=ClaimReviewRequest(review_status="rejected"),
                        db=db,
                        current_user=owner,
                    )
            self.assertEqual(no_evidence_ctx.exception.status_code, 409)
            self.assertEqual(foreign_ctx.exception.status_code, 404)
            self.assertNotIn("Private grounded statement", str(foreign_ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
