"""Real Graphiti 0.30.x + Neo4j Stage 6 search integration without model calls.

Run explicitly with:

    RUN_GRAPHITI_INTEGRATION=1 \
    NEO4J_URI=bolt://127.0.0.1:17687 \
    NEO4J_USER=neo4j \
    NEO4J_PASSWORD=stage6-graphiti-test \
    PYTHONPATH=. venv/bin/python -m pytest -q tests/test_graphiti_shadow_integration.py

The test seeds Graphiti nodes/edges directly and uses BM25-only search.  Any LLM,
embedding, or cross-encoder call raises immediately, so the integration proves
group scoping and temporal filtering without consuming an external model quota.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.graphiti_shadow_service import GraphitiShadowAdapter, graphiti_group_id


RUN = os.getenv("RUN_GRAPHITI_INTEGRATION", "").strip() == "1"
HAS_GRAPHITI = importlib.util.find_spec("graphiti_core") is not None


if HAS_GRAPHITI:
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import LLMClient

    class _NoLlmCalls(LLMClient):
        def __init__(self):
            super().__init__(config=None, cache=False)

        async def _generate_response(self, *_args, **_kwargs):
            raise AssertionError("unexpected external LLM call")

    class _NoEmbeddingCalls(EmbedderClient):
        async def create(self, _input_data):
            raise AssertionError("unexpected external embedding call")

    class _NoCrossEncoderCalls(CrossEncoderClient):
        async def rank(self, _query: str, _passages: list[str]):
            raise AssertionError("unexpected external reranker call")
else:  # pragma: no cover - optional dependency branch
    _NoLlmCalls = _NoEmbeddingCalls = _NoCrossEncoderCalls = object


@unittest.skipUnless(RUN and HAS_GRAPHITI, "requires explicit Graphiti integration environment")
class GraphitiShadowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'graphiti-stage6.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_real_graphiti_bm25_search_is_group_scoped_temporal_and_zero_model(self):
        from graphiti_core import Graphiti
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode
        from graphiti_core.search.search_config import (
            EdgeReranker,
            EdgeSearchConfig,
            EdgeSearchMethod,
            SearchConfig,
        )

        uri = os.environ["NEO4J_URI"]
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "stage6-graphiti-test")
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        driver = Neo4jDriver(uri=uri, user=user, password=password, database=database)
        graphiti = Graphiti(
            graph_driver=driver,
            llm_client=_NoLlmCalls(),
            embedder=_NoEmbeddingCalls(),
            cross_encoder=_NoCrossEncoderCalls(),
            store_raw_episode_content=False,
        )
        group_id = graphiti_group_id(7001)
        foreign_group = graphiti_group_id(7002)
        now = datetime.now(timezone.utc)
        local_zero_embedding = [0.0] * 1024
        try:
            await driver.execute_query("MATCH (n) DETACH DELETE n")
            await graphiti.build_indices_and_constraints()

            owner = EntityNode(
                uuid="stage6-graphiti-owner",
                name="User",
                group_id=group_id,
                created_at=now,
                name_embedding=local_zero_embedding,
            )
            goal = EntityNode(
                uuid="stage6-graphiti-goal",
                name="Career Goal",
                group_id=group_id,
                created_at=now,
                name_embedding=local_zero_embedding,
            )
            foreign = EntityNode(
                uuid="stage6-graphiti-foreign",
                name="Career Goal",
                group_id=foreign_group,
                created_at=now,
                name_embedding=local_zero_embedding,
            )
            await owner.save(driver)
            await goal.save(driver)
            await foreign.save(driver)

            old_edge = EntityEdge(
                uuid="stage6-graphiti-old",
                group_id=group_id,
                source_node_uuid=owner.uuid,
                target_node_uuid=goal.uuid,
                created_at=now - timedelta(days=20),
                name="career_goal",
                fact="career goal was learn retrieval augmented generation",
                fact_embedding=local_zero_embedding,
                episodes=["mnemox-memory-declaration-7001-101"],
                valid_at=now - timedelta(days=20),
                invalid_at=now - timedelta(days=5),
                reference_time=now - timedelta(days=20),
            )
            current_edge = EntityEdge(
                uuid="stage6-graphiti-current",
                group_id=group_id,
                source_node_uuid=owner.uuid,
                target_node_uuid=goal.uuid,
                created_at=now - timedelta(days=5),
                name="career_goal",
                fact="career goal is build agent systems",
                fact_embedding=local_zero_embedding,
                episodes=["mnemox-memory-declaration-7001-102"],
                valid_at=now - timedelta(days=5),
                invalid_at=None,
                reference_time=now - timedelta(days=5),
            )
            foreign_edge = EntityEdge(
                uuid="stage6-graphiti-foreign-edge",
                group_id=foreign_group,
                source_node_uuid=foreign.uuid,
                target_node_uuid=foreign.uuid,
                created_at=now,
                name="career_goal",
                fact="career goal is private foreign value",
                fact_embedding=local_zero_embedding,
                episodes=["mnemox-memory-declaration-7002-999"],
                valid_at=now - timedelta(days=1),
                invalid_at=None,
                reference_time=now - timedelta(days=1),
            )
            await old_edge.save(driver)
            await current_edge.save(driver)
            await foreign_edge.save(driver)

            search_config = SearchConfig(
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bm25],
                    reranker=EdgeReranker.rrf,
                ),
                limit=20,
            )

            class _Bm25Client:
                def __init__(self, graph):
                    self.graph = graph
                    self.driver = graph.driver

                async def search(self, query: str, *, group_ids=None, num_results=10, **_kwargs):
                    search_config.limit = int(num_results)
                    result = await self.graph.search_(
                        str(query),
                        config=search_config,
                        group_ids=list(group_ids or []),
                    )
                    return list(result.edges)

                async def close(self):
                    return None

            async with self.sessions() as db:
                adapter = GraphitiShadowAdapter(
                    db,
                    client=_Bm25Client(graphiti),
                    episode_type=None,
                )
                current = await adapter.search_temporal(
                    user_id=7001,
                    query="career goal agent systems retrieval generation",
                    as_of=now,
                    limit=10,
                )
                historical = await adapter.search_temporal(
                    user_id=7001,
                    query="career goal retrieval generation agent systems",
                    as_of=now - timedelta(days=10),
                    limit=10,
                )

            self.assertEqual(current.declaration_ids, (102,))
            self.assertEqual(historical.declaration_ids, (101,))
            self.assertNotIn(999, current.declaration_ids)
            self.assertNotIn(999, historical.declaration_ids)
            self.assertFalse(graphiti.store_raw_episode_content)
        finally:
            await graphiti.close()


if __name__ == "__main__":
    unittest.main()
