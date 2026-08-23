"""Concept identity, reviewed provenance, material cleanup and tenant isolation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.models.concept import Concept, ConceptAlias, ConceptAuditEvent, ConceptEdge, ConceptLink, ConceptSourceEvidence
from app.models.material import Chapter, Material
from app.models.retrieval import RetrievalProjection
from app.models.user import User
from app.services.concept_graph_service import (
    add_concept_alias,
    create_concept_relation,
    delete_concept,
    forget_material_concepts,
    get_concept_detail,
    get_prerequisite_gaps,
    merge_concepts,
    rename_concept,
    review_concept,
    split_concept,
    sync_material_concepts,
)
from app.services.concept_service import add_edge, link_concept, upsert_concept
from app.services.learner_model_service import record_evidence
from app.services.learning_event_service import record_learning_event
from app.services.retrieval_router import RetrievalRouter
from app.services.material_service import MaterialService


class _NoEmbeddingRag:
    _current_model = "graph-test"
    _current_base_url = "https://embedding.invalid/v1"
    _chunk_size = 256
    _chunk_overlap = 0

    async def initialize(self):
        return None

    async def get_status(self, _user_id):
        return {"embedding_enabled": False}

    async def remove_material(self, _material_id, *, user_id=None):
        return None


class ConceptGraphClosureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        database = Path(self.tmpdir.name) / "concept_graph_closure.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.owner = await self._create_user("concept-closure-owner")
        self.other = await self._create_user("concept-closure-other")

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessions() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            result = int(user.id)
            await session.commit()
            return result

    async def _material(self, session, content: str) -> Material:
        material = Material(user_id=self.owner, title="检索系统", content=content, content_status="extracted")
        session.add(material)
        await session.flush()
        session.add(RetrievalProjection(user_id=self.owner, source_id=int(material.id), source_version=1))
        await session.flush()
        return material

    async def test_material_candidates_aliases_and_edges_require_human_confirmation(self):
        async with self.sessions() as session:
            material = await self._material(
                session,
                "## 混合检索\n## RRF\nRRF (Reciprocal Rank Fusion)\n混合检索 -> RRF\n",
            )
            result = await sync_material_concepts(session, self.owner, material)
            self.assertEqual(result["status"], "pending_review")
            self.assertGreaterEqual(result["created_concepts"], 2)
            self.assertEqual(result["created_edges"], 1)

            rrf = await session.scalar(select(Concept).where(Concept.user_id == self.owner, Concept.name == "RRF"))
            hybrid = await session.scalar(select(Concept).where(Concept.user_id == self.owner, Concept.name == "混合检索"))
            self.assertEqual(rrf.review_status, "pending")
            self.assertEqual(await get_prerequisite_gaps(session, self.owner, int(rrf.id)), [])
            router = RetrievalRouter(session)
            pending_hits = await router.search(
                "RRF", user_id=self.owner, source_types=("concept", "learner_state"),
            )
            self.assertEqual(pending_hits, [])
            detail = await get_concept_detail(session, self.owner, int(rrf.id))
            self.assertIn("Reciprocal Rank Fusion", [item["alias"] for item in detail["aliases"]])
            self.assertTrue(all(item["review_status"] == "pending" for item in detail["source_evidence"]))

            await review_concept(session, self.owner, int(hybrid.id), "confirmed")
            await review_concept(session, self.owner, int(rrf.id), "confirmed")
            gaps = await get_prerequisite_gaps(session, self.owner, int(rrf.id))
            self.assertEqual([item["name"] for item in gaps], ["混合检索"])
            edge = await session.scalar(select(ConceptEdge).where(ConceptEdge.user_id == self.owner))
            self.assertEqual(edge.review_status, "confirmed")
            approved_hits = await router.search(
                "RRF", user_id=self.owner, source_types=("concept", "learner_state"),
            )
            self.assertTrue(approved_hits)
            alias_hits = await router.search(
                "Reciprocal Rank Fusion", user_id=self.owner, source_types=("concept",),
            )
            self.assertEqual(int(alias_hits[0].source_id), int(rrf.id))

    async def test_update_replaces_old_source_evidence_and_delete_leaves_no_graph_residue(self):
        async with self.sessions() as session:
            material = await self._material(session, "## 旧概念\n旧概念：这个知识点将在更新后消失。")
            await sync_material_concepts(session, self.owner, material)
            projection = await session.scalar(
                select(RetrievalProjection).where(RetrievalProjection.source_id == int(material.id))
            )
            projection.source_version = 2
            material.content = "## 新概念\n新概念：更新后的正式知识点。"
            await session.flush()
            result = await sync_material_concepts(session, self.owner, material)
            self.assertEqual(result["source_version"], 2)
            current = (
                await session.execute(
                    select(ConceptSourceEvidence).where(ConceptSourceEvidence.source_id == int(material.id))
                )
            ).scalars().all()
            self.assertTrue(current)
            self.assertTrue(all(int(item.source_version) == 2 for item in current))
            self.assertIsNone(
                await session.scalar(select(Concept.id).where(Concept.user_id == self.owner, Concept.name == "旧概念"))
            )

            await forget_material_concepts(session, self.owner, int(material.id))
            residue = await session.scalar(
                select(ConceptSourceEvidence.id).where(
                    ConceptSourceEvidence.user_id == self.owner, ConceptSourceEvidence.source_id == int(material.id),
                )
            )
            self.assertIsNone(residue)

    async def test_alias_rename_merge_split_and_delete_are_audited(self):
        async with self.sessions() as session:
            material = await self._material(session, "普通文本，不自动抽取概念。")
            canonical = await upsert_concept(session, self.owner, "RRF", source="manual")
            duplicate = await upsert_concept(session, self.owner, "倒数排名融合", source="manual")
            await add_concept_alias(session, self.owner, int(canonical.id), "Reciprocal Rank Fusion")
            resolved = await upsert_concept(session, self.owner, "reciprocal rank fusion")
            self.assertEqual(int(resolved.id), int(canonical.id))
            await link_concept(session, self.owner, int(duplicate.id), "material", int(material.id))

            learning_event = await record_learning_event(
                session, self.owner, "practice.answer", source="test",
                payload={"concept_id": int(duplicate.id), "score": 0.3},
            )
            await record_evidence(
                session, self.owner, int(duplicate.id), "answer", score=0.3, reliability=1,
                source_event_id=int(learning_event["id"]), source_type="test",
            )
            merged = await merge_concepts(session, self.owner, int(canonical.id), int(duplicate.id))
            self.assertEqual(merged["merge"]["migrated"]["learner_evidence"], 1)
            self.assertIn("倒数排名融合", [item["alias"] for item in merged["aliases"]])

            renamed = await rename_concept(session, self.owner, int(canonical.id), name="排序融合")
            self.assertIn("RRF", [item["alias"] for item in renamed["aliases"]])
            alias = next(item for item in renamed["aliases"] if item["alias"] == "倒数排名融合")
            separated = await split_concept(
                session, self.owner, int(canonical.id), name="排名融合变体", alias_ids=[int(alias["id"])],
            )
            self.assertEqual(separated["split"]["moved"]["aliases"], 1)
            deleted = await delete_concept(session, self.owner, int(separated["id"]))
            self.assertTrue(deleted["deleted"])
            audit = (
                await session.execute(select(ConceptAuditEvent).where(ConceptAuditEvent.user_id == self.owner))
            ).scalars().all()
            self.assertTrue({"merged", "renamed", "split", "deleted"}.issubset({row.operation for row in audit}))

    async def test_edges_reject_foreign_concepts_and_prerequisite_cycles(self):
        async with self.sessions() as session:
            first = await upsert_concept(session, self.owner, "第一概念")
            second = await upsert_concept(session, self.owner, "第二概念")
            foreign = await upsert_concept(session, self.other, "其他用户概念")
            self.assertFalse(await add_edge(session, self.owner, int(first.id), int(foreign.id), "related_to"))
            await create_concept_relation(session, self.owner, int(first.id), int(second.id), "prerequisite")
            self.assertFalse(await add_edge(session, self.owner, int(second.id), int(first.id), "prerequisite_of"))
            with self.assertRaises(LookupError):
                await merge_concepts(session, self.owner, int(first.id), int(foreign.id))

    async def test_material_service_automatically_extracts_refreshes_and_forgets_concepts(self):
        async with self.sessions() as session:
            with patch("app.services.material_service.get_rag_service", return_value=_NoEmbeddingRag()):
                service = MaterialService(session)
                created = await service.create_material(
                    title="自动图谱", content="## 旧知识点\n旧知识点：上传后自动出现。",
                    user_id=self.owner, sync_to_rag=False,
                )
                material_id = int(created.id)
                old = await session.scalar(
                    select(Concept.id).where(Concept.user_id == self.owner, Concept.name == "旧知识点")
                )
                self.assertIsNotNone(old)

                await service.update_material(
                    material_id, user_id=self.owner, content="## 新知识点\n新知识点：更新后重新抽取。",
                )
                stale = await session.scalar(
                    select(Concept.id).where(Concept.user_id == self.owner, Concept.name == "旧知识点")
                )
                fresh = await session.scalar(
                    select(Concept.id).where(Concept.user_id == self.owner, Concept.name == "新知识点")
                )
                self.assertIsNone(stale)
                self.assertIsNotNone(fresh)
                chapter = Chapter(material_id=material_id, title="图谱章节", content="章节内容", order_index=1)
                session.add(chapter)
                await session.flush()
                chapter_id = int(chapter.id)
                await link_concept(session, self.owner, int(fresh), "chapter", chapter_id)

                self.assertTrue(await service.delete_material(material_id, user_id=self.owner))
                residue = await session.scalar(
                    select(ConceptSourceEvidence.id).where(
                        ConceptSourceEvidence.user_id == self.owner,
                        ConceptSourceEvidence.source_type == "material",
                        ConceptSourceEvidence.source_id == material_id,
                    )
                )
                self.assertIsNone(residue)
                stale_link = await session.scalar(
                    select(ConceptLink.id).where(
                        ConceptLink.user_id == self.owner, ConceptLink.target_type == "chapter",
                        ConceptLink.target_id == chapter_id,
                    )
                )
                self.assertIsNone(stale_link)


if __name__ == "__main__":
    unittest.main()
