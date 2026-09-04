"""Stage 1 canonical Source/Revision/Unit/Claim/Evidence lifecycle gates."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.config import settings
from app.models.knowledge import (
    Claim,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.material import Material
from app.models.user import User
from app.services.knowledge_source_service import (
    claim_fingerprint,
    create_manual_claim,
    delete_source,
    list_visible_claims,
    register_material_source,
    review_claim,
)
from app.services.material_service import MaterialService
from app.routers.notes import NoteCreate, NoteUpdate, create_note, delete_note, update_note


class KnowledgeSourceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'knowledge.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, username: str) -> int:
        async with self.sessions() as db:
            user = User(
                username=username,
                email=f"{username}@example.test",
                hashed_password="hash",
            )
            db.add(user)
            await db.commit()
            return int(user.id)

    async def _material(self, user_id: int, title: str, content: str) -> int:
        async with self.sessions() as db:
            material = Material(
                user_id=int(user_id),
                title=title,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
            db.add(material)
            await db.commit()
            return int(material.id)

    async def test_source_registration_is_idempotent_and_manual_claim_is_grounded(self) -> None:
        user_id = await self._user("knowledge-owner")
        material_id = await self._material(
            user_id,
            "Grounding",
            "Evidence grounds every visible claim.",
        )

        async with self.sessions() as db:
            first = await register_material_source(db, user_id=user_id, material_id=material_id)
            repeated = await register_material_source(db, user_id=user_id, material_id=material_id)
            unit = await db.scalar(
                select(KnowledgeUnit).where(KnowledgeUnit.source_revision_id == int(first.id))
            )
            self.assertIsNotNone(unit)
            claim = await create_manual_claim(
                db,
                user_id=user_id,
                source_revision_id=int(first.id),
                knowledge_unit_id=int(unit.id),
                statement="Every visible Claim needs evidence.",
                excerpt="Evidence grounds every visible claim.",
            )
            duplicate = await create_manual_claim(
                db,
                user_id=user_id,
                source_revision_id=int(first.id),
                knowledge_unit_id=int(unit.id),
                statement="every visible claim needs evidence",
                excerpt="Evidence grounds every visible claim.",
            )
            await db.commit()
            visible = await list_visible_claims(db, user_id=user_id)
            evidence_count = await db.scalar(
                select(func.count()).select_from(ClaimEvidence).where(
                    ClaimEvidence.claim_id == int(claim.id)
                )
            )

        self.assertEqual(first.id, repeated.id)
        self.assertEqual(first.revision, 1)
        self.assertEqual(claim.id, duplicate.id)
        self.assertEqual(claim_fingerprint("Ａ Claim!"), claim_fingerprint("a claim"))
        self.assertEqual([row.id for row in visible], [claim.id])
        self.assertEqual(evidence_count, 1)

    async def test_source_update_supersedes_prior_revision_and_claim(self) -> None:
        user_id = await self._user("revision-owner")
        material_id = await self._material(user_id, "Version one", "old grounded statement")

        async with self.sessions() as db:
            first = await register_material_source(db, user_id=user_id, material_id=material_id)
            unit = await db.scalar(
                select(KnowledgeUnit).where(KnowledgeUnit.source_revision_id == int(first.id))
            )
            old_claim = await create_manual_claim(
                db,
                user_id=user_id,
                source_revision_id=int(first.id),
                knowledge_unit_id=int(unit.id),
                statement="This is the old statement.",
                excerpt="old grounded statement",
            )
            material = await db.get(Material, material_id)
            material.title = "Version two"
            material.content = "new grounded statement"
            material.content_hash = hashlib.sha256(material.content.encode()).hexdigest()
            second = await register_material_source(db, user_id=user_id, material_id=material_id)
            await db.commit()

            revisions = list(
                (
                    await db.scalars(
                        select(KnowledgeSourceRevision)
                        .where(KnowledgeSourceRevision.knowledge_source_id == first.knowledge_source_id)
                        .order_by(KnowledgeSourceRevision.revision)
                    )
                ).all()
            )
            current_count = await db.scalar(
                select(func.count())
                .select_from(KnowledgeSourceRevision)
                .where(
                    KnowledgeSourceRevision.knowledge_source_id == first.knowledge_source_id,
                    KnowledgeSourceRevision.status == "current",
                )
            )
            await db.refresh(old_claim)
            visible = await list_visible_claims(db, user_id=user_id)

        self.assertEqual(second.revision, 2)
        self.assertEqual([row.status for row in revisions], ["superseded", "current"])
        self.assertEqual(current_count, 1)
        self.assertEqual(old_claim.lifecycle_status, "superseded")
        self.assertEqual(visible, [])

    async def test_source_delete_tombstones_and_redacts_derived_content(self) -> None:
        user_id = await self._user("delete-owner")
        material_id = await self._material(user_id, "Private", "private evidence text")

        async with self.sessions() as db:
            revision = await register_material_source(db, user_id=user_id, material_id=material_id)
            unit = await db.scalar(
                select(KnowledgeUnit).where(KnowledgeUnit.source_revision_id == int(revision.id))
            )
            claim = await create_manual_claim(
                db,
                user_id=user_id,
                source_revision_id=int(revision.id),
                knowledge_unit_id=int(unit.id),
                statement="Private source statement",
                excerpt="private evidence text",
            )
            await delete_source(
                db,
                user_id=user_id,
                source_type="material",
                source_record_id=material_id,
            )
            await db.commit()
            source = await db.scalar(
                select(KnowledgeSource).where(
                    KnowledgeSource.user_id == user_id,
                    KnowledgeSource.source_record_id == material_id,
                )
            )
            await db.refresh(revision)
            await db.refresh(unit)
            await db.refresh(claim)
            evidence = await db.scalar(
                select(ClaimEvidence).where(ClaimEvidence.claim_id == int(claim.id))
            )
            visible = await list_visible_claims(db, user_id=user_id)

        self.assertEqual(source.status, "deleted")
        self.assertEqual(source.title_snapshot, "")
        self.assertEqual(revision.status, "deleted")
        self.assertEqual(unit.text, "")
        self.assertEqual(claim.lifecycle_status, "deleted")
        self.assertEqual(claim.statement, "")
        self.assertEqual(evidence.excerpt, "")
        self.assertEqual(visible, [])

    async def test_cross_user_source_revision_unit_and_claim_ids_are_rejected(self) -> None:
        owner = await self._user("isolation-owner")
        outsider = await self._user("isolation-outsider")
        material_id = await self._material(owner, "Owned", "owner-only evidence")

        async with self.sessions() as db:
            with self.assertRaises(PermissionError):
                await register_material_source(db, user_id=outsider, material_id=material_id)
            revision = await register_material_source(db, user_id=owner, material_id=material_id)
            unit = await db.scalar(
                select(KnowledgeUnit).where(KnowledgeUnit.source_revision_id == int(revision.id))
            )
            with self.assertRaises(PermissionError):
                await create_manual_claim(
                    db,
                    user_id=outsider,
                    source_revision_id=int(revision.id),
                    knowledge_unit_id=int(unit.id),
                    statement="stolen claim",
                    excerpt="owner-only evidence",
                )

    async def test_review_requires_ownership_active_lifecycle_and_evidence(self) -> None:
        owner = await self._user("review-owner")
        outsider = await self._user("review-outsider")
        material_id = await self._material(owner, "Review", "review evidence")

        async with self.sessions() as db:
            revision = await register_material_source(db, user_id=owner, material_id=material_id)
            pending = Claim(
                user_id=owner,
                source_revision_id=int(revision.id),
                statement="Pending without evidence",
                claim_kind="observation",
                fingerprint=claim_fingerprint("Pending without evidence"),
                confidence=0.5,
                derivation_type="explicit",
                review_status="pending",
                lifecycle_status="active",
                schema_version=1,
            )
            db.add(pending)
            await db.flush()
            with self.assertRaises(PermissionError):
                await review_claim(
                    db,
                    user_id=outsider,
                    claim_id=int(pending.id),
                    review_status="confirmed",
                )
            with self.assertRaises(ValueError):
                await review_claim(
                    db,
                    user_id=owner,
                    claim_id=int(pending.id),
                    review_status="confirmed",
                )
            rejected = await review_claim(
                db,
                user_id=owner,
                claim_id=int(pending.id),
                review_status="rejected",
            )
            self.assertEqual(rejected.review_status, "rejected")

    async def test_partial_unique_index_allows_only_one_current_revision(self) -> None:
        user_id = await self._user("current-revision-owner")
        material_id = await self._material(user_id, "Current", "current source")

        async with self.sessions() as db:
            current = await register_material_source(db, user_id=user_id, material_id=material_id)
            db.add(
                KnowledgeSourceRevision(
                    user_id=user_id,
                    knowledge_source_id=int(current.knowledge_source_id),
                    revision=2,
                    content_hash="f" * 64,
                    title_snapshot="Duplicate current",
                    status="current",
                )
            )
            with self.assertRaises(IntegrityError):
                await db.flush()
            await db.rollback()

    async def test_revision_number_is_unique_even_when_status_is_not_current(self) -> None:
        user_id = await self._user("revision-number-owner")
        material_id = await self._material(user_id, "Revision", "canonical source")

        async with self.sessions() as db:
            current = await register_material_source(db, user_id=user_id, material_id=material_id)
            db.add(
                KnowledgeSourceRevision(
                    user_id=user_id,
                    knowledge_source_id=int(current.knowledge_source_id),
                    revision=1,
                    content_hash="e" * 64,
                    title_snapshot="Duplicate number",
                    status="superseded",
                )
            )
            with self.assertRaises(IntegrityError):
                await db.flush()
            await db.rollback()

    async def test_deleting_canonical_source_cascades_all_derived_rows(self) -> None:
        user_id = await self._user("cascade-owner")
        material_id = await self._material(user_id, "Cascade", "cascade evidence")

        async with self.sessions() as db:
            revision = await register_material_source(db, user_id=user_id, material_id=material_id)
            unit = await db.scalar(
                select(KnowledgeUnit).where(KnowledgeUnit.source_revision_id == int(revision.id))
            )
            claim = await create_manual_claim(
                db,
                user_id=user_id,
                source_revision_id=int(revision.id),
                knowledge_unit_id=int(unit.id),
                statement="Cascade removes derived rows.",
                excerpt="cascade evidence",
            )
            source_id = int(revision.knowledge_source_id)
            claim_id = int(claim.id)
            await db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
            await db.commit()

            counts = {
                "revisions": await db.scalar(
                    select(func.count()).select_from(KnowledgeSourceRevision).where(
                        KnowledgeSourceRevision.knowledge_source_id == source_id
                    )
                ),
                "units": await db.scalar(
                    select(func.count()).select_from(KnowledgeUnit).where(
                        KnowledgeUnit.source_revision_id == int(revision.id)
                    )
                ),
                "claims": await db.scalar(
                    select(func.count()).select_from(Claim).where(Claim.id == claim_id)
                ),
                "evidence": await db.scalar(
                    select(func.count()).select_from(ClaimEvidence).where(
                        ClaimEvidence.claim_id == claim_id
                    )
                ),
            }

        self.assertEqual(counts, {"revisions": 0, "units": 0, "claims": 0, "evidence": 0})

    async def test_disabled_feature_flag_does_not_register_material_source(self) -> None:
        user_id = await self._user("disabled-flag-owner")
        async with self.sessions() as db:
            service = MaterialService(db)
            with (
                patch.object(settings, "KNOWLEDGE_V2_ENABLED", False),
                patch.object(
                    service.projections,
                    "ingest",
                    AsyncMock(return_value={"status": "degraded"}),
                ),
                patch(
                    "app.services.material_service.sync_material_concepts",
                    AsyncMock(return_value={"status": "skipped"}),
                ),
            ):
                material = await service.create_material(
                    title="Legacy-only material",
                    content="the canonical feature remains disabled",
                    sync_to_rag=False,
                    user_id=user_id,
                )

            self.assertIsNotNone(material.id)
            self.assertEqual(
                await db.scalar(select(func.count()).select_from(KnowledgeSource)),
                0,
            )

    async def test_material_write_path_registers_revisions_without_auto_claims(self) -> None:
        user_id = await self._user("material-integration-owner")
        async with self.sessions() as db:
            service = MaterialService(db)
            with (
                patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
                patch.object(
                    service.projections,
                    "ingest",
                    AsyncMock(return_value={"status": "degraded"}),
                ),
                patch.object(
                    service.projections,
                    "refresh",
                    AsyncMock(return_value={"status": "degraded"}),
                ),
                patch.object(
                    service.projections,
                    "forget",
                    AsyncMock(return_value={"status": "deleted"}),
                ),
                patch(
                    "app.services.material_service.sync_material_concepts",
                    AsyncMock(return_value={"status": "skipped"}),
                ),
                patch(
                    "app.services.material_service.forget_material_concepts",
                    AsyncMock(return_value=None),
                ),
            ):
                material = await service.create_material(
                    title="Stage 1 material",
                    content="first canonical body",
                    sync_to_rag=False,
                    user_id=user_id,
                )
                material_id = int(material.id)
                source = await db.scalar(
                    select(KnowledgeSource).where(
                        KnowledgeSource.user_id == user_id,
                        KnowledgeSource.source_type == "material",
                        KnowledgeSource.source_record_id == material_id,
                    )
                )
                self.assertIsNotNone(source)
                self.assertEqual(source.current_revision, 1)
                self.assertEqual(
                    await db.scalar(select(func.count()).select_from(Claim)),
                    0,
                )

                await service.update_material(
                    material_id,
                    user_id=user_id,
                    content="second canonical body",
                )
                await db.refresh(source)
                self.assertEqual(source.current_revision, 2)

                self.assertTrue(await service.delete_material(material_id, user_id=user_id))
                await db.refresh(source)
                self.assertEqual(source.status, "deleted")

    async def test_note_write_path_registers_revisions_without_changing_association_v1(self) -> None:
        user_id = await self._user("note-integration-owner")
        async with self.sessions() as db:
            user = await db.get(User, user_id)
            with (
                patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
                patch(
                    "app.services.association_service.attach_note_to_concepts",
                    AsyncMock(return_value=[]),
                ),
                patch(
                    "app.services.association_service.find_associations",
                    AsyncMock(return_value=[]),
                ),
                patch(
                    "app.services.association_service.detach_note_from_concepts",
                    AsyncMock(return_value=None),
                ),
            ):
                created = await create_note(
                    NoteCreate(title="Stage 1 note", content="first note body"),
                    db=db,
                    current_user=user,
                )
                note_id = int(created["id"])
                await db.commit()
                source = await db.scalar(
                    select(KnowledgeSource).where(
                        KnowledgeSource.user_id == user_id,
                        KnowledgeSource.source_type == "note",
                        KnowledgeSource.source_record_id == note_id,
                    )
                )
                self.assertIsNotNone(source)
                self.assertEqual(source.current_revision, 1)
                self.assertEqual(created["associations"], [])

                await update_note(
                    note_id,
                    NoteUpdate(content="second note body"),
                    db=db,
                    current_user=user,
                )
                await db.refresh(source)
                self.assertEqual(source.current_revision, 2)

                await delete_note(note_id, db=db, current_user=user)
                await db.refresh(source)
                self.assertEqual(source.status, "deleted")


if __name__ == "__main__":
    unittest.main()
