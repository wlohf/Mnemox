"""Stage 6 Graphiti shadow benchmark with zero external model calls.

The benchmark compares Mnemox's existing confirmed-memory SQL retrieval with a
real graphiti-core 0.30.x BM25-only search over the same synthetic facts.  The
Graphiti graph is seeded directly with deterministic local zero vectors, so any
LLM, embedding, or cross-encoder call is a test failure rather than a hidden
cost.  SQL remains authoritative throughout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.services.graphiti_shadow_service import GraphitiShadowAdapter, graphiti_group_id
from app.services.retrieval_router import RetrievalRouter


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(len(ordered) - 1, lower + 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _latency(values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": round(statistics.mean(values), 3) if values else 0.0,
        "p50_ms": round(_percentile(values, 0.50), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
    }


async def _run_case(
    *,
    count: int,
    query_count: int,
    uri: str,
    neo4j_user: str,
    neo4j_password: str,
    database: str,
) -> dict[str, Any]:
    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.search.search_config import (
        EdgeReranker,
        EdgeSearchConfig,
        EdgeSearchMethod,
        SearchConfig,
    )

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

    user_id = 8100 + int(count)
    group_id = graphiti_group_id(user_id)
    now = datetime.now(timezone.utc)
    local_zero_embedding = [0.0] * 1024
    driver = Neo4jDriver(
        uri=str(uri),
        user=str(neo4j_user),
        password=str(neo4j_password),
        database=str(database),
    )
    graphiti = Graphiti(
        graph_driver=driver,
        llm_client=_NoLlmCalls(),
        embedder=_NoEmbeddingCalls(),
        cross_encoder=_NoCrossEncoderCalls(),
        store_raw_episode_content=False,
    )
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

    try:
        await driver.execute_query("MATCH (n) DETACH DELETE n")
        await graphiti.build_indices_and_constraints()
        with tempfile.TemporaryDirectory() as tmp:
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{Path(tmp) / f'graphiti-{count}.db'}"
            )
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                sessions = async_sessionmaker(engine, expire_on_commit=False)
                async with sessions() as db:
                    user = User(
                        id=user_id,
                        username=f"graphiti-benchmark-{count}",
                        email=f"graphiti-benchmark-{count}@example.test",
                        hashed_password="hash",
                    )
                    db.add(user)
                    await db.flush()
                    rows: list[dict[str, Any]] = []
                    declaration_ids: list[int] = []
                    for index in range(int(count)):
                        token = f"token{index:05d}"
                        value = f"benchmark career goal {token} build agent system topic {index:05d}"
                        memory = UserMemory(
                            user_id=user_id,
                            memory_key=f"career_goal_{index:05d}",
                            memory_value=value,
                            category="goal",
                            confidence=0.9,
                            status="active",
                            review_status="confirmed",
                            memory_type="semantic",
                        )
                        db.add(memory)
                        await db.flush()
                        declaration = MemoryDeclaration(
                            user_id=user_id,
                            memory_id=int(memory.id),
                            subject="user",
                            predicate="career_goal",
                            fact_key=f"goal:{index:05d}",
                            value=value,
                            valid_from=now.replace(tzinfo=None) - timedelta(days=1),
                            valid_to=None,
                            observed_at=now.replace(tzinfo=None) - timedelta(days=1),
                            confidence=1.0,
                            review_status="confirmed",
                            source_type="manual",
                            created_by="user",
                        )
                        db.add(declaration)
                        await db.flush()
                        declaration_ids.append(int(declaration.id))
                        rows.append(
                            {
                                "source_uuid": f"graphiti-bench-source-{user_id}-{index}",
                                "target_uuid": f"graphiti-bench-target-{user_id}-{index}",
                                "edge_uuid": f"graphiti-bench-edge-{user_id}-{index}",
                                "group_id": group_id,
                                "name": "career_goal",
                                "fact": value,
                                "episode_uuid": (
                                    f"mnemox-memory-declaration-{user_id}-{int(declaration.id)}"
                                ),
                                "created_at": now,
                                "valid_at": now - timedelta(days=1),
                            }
                        )
                    await db.commit()

                seed_started = time.perf_counter()
                await driver.execute_query(
                    """
                    UNWIND $rows AS row
                    MERGE (source:Entity {uuid: row.source_uuid})
                    SET source.name = 'User', source.group_id = row.group_id,
                        source.created_at = row.created_at, source.name_embedding = $embedding
                    MERGE (target:Entity {uuid: row.target_uuid})
                    SET target.name = row.name, target.group_id = row.group_id,
                        target.created_at = row.created_at, target.name_embedding = $embedding
                    MERGE (source)-[edge:RELATES_TO {uuid: row.edge_uuid}]->(target)
                    SET edge.group_id = row.group_id, edge.name = row.name, edge.fact = row.fact,
                        edge.fact_embedding = $embedding, edge.episodes = [row.episode_uuid],
                        edge.created_at = row.created_at, edge.valid_at = row.valid_at,
                        edge.invalid_at = null, edge.expired_at = null,
                        edge.reference_time = row.created_at
                    """,
                    params={"rows": rows, "embedding": local_zero_embedding},
                )
                seed_ms = (time.perf_counter() - seed_started) * 1000.0

                anchors = [
                    min(count - 1, round(index * (count - 1) / max(1, query_count - 1)))
                    for index in range(max(1, query_count))
                ]
                sql_times: list[float] = []
                graphiti_times: list[float] = []
                sql_hits = 0
                graphiti_hits = 0
                async with sessions() as db:
                    router = RetrievalRouter.__new__(RetrievalRouter)
                    router.db = db
                    adapter = GraphitiShadowAdapter(
                        db,
                        client=_Bm25Client(graphiti),
                        episode_type=None,
                    )
                    for index in anchors:
                        token = f"token{index:05d}"
                        # Use the unique token shared by SQL memory_value and
                        # Graphiti fact so recall compares the same retrieval
                        # problem rather than candidate-budget behavior on
                        # common terms.
                        query = token
                        started = time.perf_counter()
                        sql_result = await RetrievalRouter._search_memories(
                            router,
                            query,
                            user_id,
                            5,
                        )
                        sql_times.append((time.perf_counter() - started) * 1000.0)
                        expected_memory_key = f"career_goal_{index:05d}"
                        if any(hit.title == expected_memory_key for hit in sql_result):
                            sql_hits += 1

                        started = time.perf_counter()
                        graph_result = await adapter.search_temporal(
                            user_id=user_id,
                            query=query,
                            as_of=now,
                            limit=5,
                        )
                        graphiti_times.append((time.perf_counter() - started) * 1000.0)
                        expected_declaration_id = declaration_ids[index]
                        if expected_declaration_id in graph_result.declaration_ids:
                            graphiti_hits += 1

                return {
                    "facts": int(count),
                    "queries": len(anchors),
                    "seed_ms": round(seed_ms, 3),
                    "sql_recall_at_5": round(sql_hits / max(1, len(anchors)), 4),
                    "graphiti_recall_at_5": round(graphiti_hits / max(1, len(anchors)), 4),
                    "sql": _latency(sql_times),
                    "graphiti_bm25": _latency(graphiti_times),
                    "external_model_calls": 0,
                    "raw_episode_storage": False,
                    "group_id": "sanitized",
                }
            finally:
                await engine.dispose()
    finally:
        await graphiti.close()


async def run(args) -> dict[str, Any]:
    results = []
    for value in str(args.sizes).split(","):
        value = value.strip()
        if value:
            results.append(
                await _run_case(
                    count=int(value),
                    query_count=max(1, int(args.queries)),
                    uri=str(args.neo4j_uri),
                    neo4j_user=str(args.neo4j_user),
                    neo4j_password=str(args.neo4j_password),
                    database=str(args.neo4j_database),
                )
            )
    return {
        "benchmark": "mnemox_stage6_graphiti_shadow_bm25_v1",
        "graphiti_mode": "real_graphiti_core_0_30_bm25_only",
        "results": results,
        "gate_snapshot": {
            "all_sql_recall": all(row["sql_recall_at_5"] == 1.0 for row in results),
            "all_graphiti_recall": all(row["graphiti_recall_at_5"] == 1.0 for row in results),
            "external_model_calls": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="stage6-graphiti-test")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--sizes", default="100,1000")
    parser.add_argument("--queries", type=int, default=30)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    gate = report["gate_snapshot"]
    return 0 if gate["all_sql_recall"] and gate["all_graphiti_recall"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
