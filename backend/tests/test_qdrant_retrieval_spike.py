"""Optional Qdrant Local spike contract tests; never required in production."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.material import Material
from app.models.user import User
from app.services.material_retrieval_backend import MaterialSearchScope
from evaluate_retrieval import DIMENSION, DeterministicEmbedding

QDRANT_AVAILABLE = importlib.util.find_spec("qdrant_client") is not None


@unittest.skipUnless(QDRANT_AVAILABLE, "optional Qdrant spike dependency is not installed")
class QdrantRetrievalSpikeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from app.services.qdrant_retrieval_spike import QdrantMaterialRetrievalSpike

        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'qdrant.db'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.db.add_all(
            [
                User(id=1, username="q-owner", email="q-owner@example.test", hashed_password="hash"),
                User(id=2, username="q-other", email="q-other@example.test", hashed_password="hash"),
            ]
        )
        await self.db.flush()
        self.db.add_all(
            [
                Material(id=11, user_id=1, title="RRF", content="RRF fusion then reranker", file_type="md"),
                Material(id=22, user_id=2, title="Private", content="private RRF reranker secret", file_type="md"),
            ]
        )
        await self.db.commit()
        self.spike = QdrantMaterialRetrievalSpike(
            self.db,
            embedding_model=DeterministicEmbedding(),
            dimension=DIMENSION,
        )
        for material in (await self.db.scalars(select(Material))).all():
            await self.spike.index_material(material, user_id=int(material.user_id))

    async def asyncTearDown(self) -> None:
        await self.db.close()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_dense_sparse_rrf_keeps_user_isolation(self) -> None:
        hits = await self.spike.search("RRF reranker", scope=MaterialSearchScope(user_id=1))
        self.assertEqual([hit.material_id for hit in hits], [11])

    async def test_sparse_only_works_without_embedding(self) -> None:
        from app.services.qdrant_retrieval_spike import QdrantMaterialRetrievalSpike

        sparse = QdrantMaterialRetrievalSpike(
            self.db,
            embedding_model=None,
            dimension=DIMENSION,
            client=self.spike.client,
            collection_name=self.spike.collection_name,
        )
        hits = await sparse.search("reranker", scope=MaterialSearchScope(user_id=1))
        self.assertEqual([hit.material_id for hit in hits], [11])

    async def test_deletion_removes_vector_without_touching_other_user(self) -> None:
        await self.spike.remove_material(11, user_id=1)
        own = await self.spike.search("RRF", scope=MaterialSearchScope(user_id=1))
        other = await self.spike.search("RRF", scope=MaterialSearchScope(user_id=2))
        self.assertEqual(own, [])
        self.assertEqual([hit.material_id for hit in other], [22])

    async def test_user_scoped_rebuild_recovers_missing_points(self) -> None:
        await self.spike.remove_material(11, user_id=1)
        chunks = await self.spike.rebuild_user(1)
        own = await self.spike.search("reranker", scope=MaterialSearchScope(user_id=1))
        other = await self.spike.search("secret", scope=MaterialSearchScope(user_id=2))
        self.assertEqual(chunks, 1)
        self.assertEqual([hit.material_id for hit in own], [11])
        self.assertEqual([hit.material_id for hit in other], [22])


if __name__ == "__main__":
    unittest.main()
