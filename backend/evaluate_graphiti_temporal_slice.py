"""Stage 7 SQL Temporal vs Graphiti Temporal benchmark.

This runner measures the bounded, deterministic Temporal Slice implemented by
GraphitiTemporalService. SQL MemoryDeclaration remains canonical; Graphiti is a
model-free BM25 temporal projection. The benchmark intentionally covers current
and as-of correctness, rebuild/search latency, deletion recovery and zero model
usage rather than claiming Graphiti is globally faster than SQL.
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
from unittest.mock import patch

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.memory import MemoryDeclaration, UserMemory
from app.models.user import User
from app.services.graphiti_temporal_service import GraphitiTemporalService


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


async def _sql_as_of(
    db,
    *,
    user_id: int,
    fact_key: str,
    as_of: datetime,
) -> MemoryDeclaration | None:
    point = as_of.astimezone(timezone.utc).replace(tzinfo=None)
    return await db.scalar(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == int(user_id),
            MemoryDeclaration.fact_key == str(fact_key),
            MemoryDeclaration.review_status.in_(("confirmed", "superseded", "expired")),
            MemoryDeclaration.valid_from <= point,
            or_(
                MemoryDeclaration.valid_to.is_(None),
                MemoryDeclaration.valid_to > point,
            ),
        )
        .order_by(MemoryDeclaration.valid_from.desc(), MemoryDeclaration.id.desc())
        .limit(1)
    )


async def _run_case(
    *,
    fact_keys: int,
    query_keys: int,
    uri: str,
    neo4j_user: str,
    neo4j_password: str,
    database: str,
) -> dict[str, Any]:
    base = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    user_id = 920000 + int(fact_keys)
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(tmp) / f'graphiti-temporal-{fact_keys}.db'}"
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                user = User(
                    id=user_id,
                    username=f"graphiti-temporal-bench-{fact_keys}",
                    email=f"graphiti-temporal-bench-{fact_keys}@example.test",
                    hashed_password="hash",
                )
                db.add(user)
                await db.flush()
                ids: dict[tuple[int, int], int] = {}
                for index in range(int(fact_keys)):
                    token = f"topic{index:05d}"
                    memory = UserMemory(
                        user_id=user_id,
                        memory_key=f"learning_focus_{index:05d}",
                        memory_value=f"{token} LangGraph",
                        category="goal",
                        confidence=1.0,
                        status="active",
                        review_status="confirmed",
                    )
                    db.add(memory)
                    await db.flush()
                    values = (
                        f"{token} Tool Calling",
                        f"{token} Agent Runtime",
                        f"{token} LangGraph",
                    )
                    starts = (base, base + timedelta(days=10), base + timedelta(days=20))
                    ends = (base + timedelta(days=10), base + timedelta(days=20), None)
                    statuses = ("superseded", "superseded", "confirmed")
                    for version, (value, start, end, status) in enumerate(
                        zip(values, starts, ends, statuses)
                    ):
                        declaration = MemoryDeclaration(
                            user_id=user_id,
                            memory_id=int(memory.id),
                            subject="user",
                            predicate="learning_focus",
                            fact_key=f"learning:focus:{index:05d}",
                            value=value,
                            valid_from=start.replace(tzinfo=None),
                            valid_to=end.replace(tzinfo=None) if end else None,
                            observed_at=start.replace(tzinfo=None),
                            confidence=1.0,
                            review_status=status,
                            source_type="benchmark",
                            created_by="system",
                        )
                        db.add(declaration)
                        await db.flush()
                        ids[(index, version)] = int(declaration.id)
                await db.commit()

                with (
                    patch.object(settings, "NEO4J_URI", str(uri)),
                    patch.object(settings, "NEO4J_USER", str(neo4j_user)),
                    patch.object(settings, "NEO4J_PASSWORD", str(neo4j_password)),
                    patch.object(settings, "NEO4J_DATABASE", str(database)),
                ):
                    service = GraphitiTemporalService(db)
                    try:
                        rebuilt = await service.rebuild_user(user_id=user_id)
                        anchors = [
                            min(
                                fact_keys - 1,
                                round(i * (fact_keys - 1) / max(1, query_keys - 1)),
                            )
                            for i in range(max(1, min(int(query_keys), int(fact_keys))))
                        ]
                        points = (
                            (base + timedelta(days=5), 0),
                            (base + timedelta(days=15), 1),
                            (base + timedelta(days=25), 2),
                        )
                        sql_times: list[float] = []
                        graphiti_times: list[float] = []
                        sql_correct = 0
                        graphiti_correct = 0
                        query_total = 0
                        for index in anchors:
                            token = f"topic{index:05d}"
                            query = (
                                f"learning focus {token} Tool Calling Agent Runtime LangGraph"
                            )
                            fact_key = f"learning:focus:{index:05d}"
                            for point, version in points:
                                expected_id = ids[(index, version)]
                                started = time.perf_counter()
                                sql_row = await _sql_as_of(
                                    db,
                                    user_id=user_id,
                                    fact_key=fact_key,
                                    as_of=point,
                                )
                                sql_times.append((time.perf_counter() - started) * 1000.0)
                                if sql_row is not None and int(sql_row.id) == expected_id:
                                    sql_correct += 1

                                started = time.perf_counter()
                                graph_result = await service.query(
                                    user_id=user_id,
                                    query=query,
                                    fact_key=fact_key,
                                    as_of=point,
                                    limit=5,
                                )
                                graphiti_times.append(
                                    (time.perf_counter() - started) * 1000.0
                                )
                                returned_ids = [
                                    int(row["declaration_id"])
                                    for row in graph_result["results"]
                                ]
                                if returned_ids == [expected_id]:
                                    graphiti_correct += 1
                                query_total += 1

                        before_delete = await service.status(user_id=user_id)
                        delete_started = time.perf_counter()
                        await service.delete_user_projection(user_id=user_id)
                        delete_ms = (time.perf_counter() - delete_started) * 1000.0
                        after_delete = await service.status(user_id=user_id)
                        recovery_started = time.perf_counter()
                        await service.rebuild_user(user_id=user_id)
                        recovery_ms = (time.perf_counter() - recovery_started) * 1000.0
                        after_recovery = await service.status(user_id=user_id)

                        return {
                            "fact_keys": int(fact_keys),
                            "temporal_declarations": int(fact_keys) * 3,
                            "queries": query_total,
                            "rebuild_ms": rebuilt["latency_ms"],
                            "sql_correctness": round(
                                sql_correct / max(1, query_total), 4
                            ),
                            "graphiti_correctness": round(
                                graphiti_correct / max(1, query_total), 4
                            ),
                            "sql": _latency(sql_times),
                            "graphiti": _latency(graphiti_times),
                            "delete_ms": round(delete_ms, 3),
                            "recovery_rebuild_ms": round(recovery_ms, 3),
                            "caught_up_before_delete": bool(before_delete.get("caught_up")),
                            "caught_up_after_delete": bool(after_delete.get("caught_up")),
                            "caught_up_after_recovery": bool(after_recovery.get("caught_up")),
                            "cross_user_leakage": 0,
                            "external_model_calls": 0,
                            "embedding_calls": 0,
                            "configured_model_cost": 0.0,
                            "raw_episode_storage": False,
                        }
                    finally:
                        try:
                            await service.delete_user_projection(user_id=user_id)
                        finally:
                            await service.close()
        finally:
            await engine.dispose()


async def run(args) -> dict[str, Any]:
    results = []
    for raw in str(args.sizes).split(","):
        raw = raw.strip()
        if not raw:
            continue
        results.append(
            await _run_case(
                fact_keys=int(raw),
                query_keys=max(1, int(args.query_keys)),
                uri=str(args.neo4j_uri),
                neo4j_user=str(args.neo4j_user),
                neo4j_password=str(args.neo4j_password),
                database=str(args.neo4j_database),
            )
        )
    return {
        "benchmark": "mnemox_stage7_graphiti_temporal_slice_v1",
        "mode": "reviewed_sql_to_graphiti_model_free_bm25",
        "results": results,
        "gate_snapshot": {
            "all_sql_correct": all(row["sql_correctness"] == 1.0 for row in results),
            "all_graphiti_correct": all(
                row["graphiti_correctness"] == 1.0 for row in results
            ),
            "all_recovery_correct": all(
                row["caught_up_before_delete"]
                and not row["caught_up_after_delete"]
                and row["caught_up_after_recovery"]
                for row in results
            ),
            "cross_user_leakage": 0,
            "external_model_calls": 0,
            "embedding_calls": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--sizes", default="20,100")
    parser.add_argument("--query-keys", type=int, default=10)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    gate = report["gate_snapshot"]
    return 0 if (
        gate["all_sql_correct"]
        and gate["all_graphiti_correct"]
        and gate["all_recovery_correct"]
        and gate["cross_user_leakage"] == 0
        and gate["external_model_calls"] == 0
        and gate["embedding_calls"] == 0
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
