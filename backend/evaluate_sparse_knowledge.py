"""Benchmark Stage 5 reference sparse search against the SQLite FTS5 spike."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.knowledge import Claim, ClaimEvidence, KnowledgeSource, KnowledgeSourceRevision, KnowledgeUnit
from app.models.user import User
from app.services.sparse_knowledge_index import (
    PostgresFtsSparseKnowledgeIndex,
    ReferenceSparseKnowledgeIndex,
    SqliteFts5SparseKnowledgeIndex,
)


QUERIES = (
    "机会成本 项目取舍",
    "feedback loop amplify cycle",
    "最小权限 服务账号",
    "retrieval practice memory",
)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


async def _seed(db, *, claim_count: int) -> int:
    user = User(username=f"sparse-bench-{claim_count}", email=f"sparse-{claim_count}@example.test", hashed_password="hash")
    db.add(user)
    await db.flush()
    source = KnowledgeSource(
        user_id=int(user.id), source_type="note", source_record_id=1, source_key="note:1",
        title_snapshot="Sparse benchmark", status="active", current_revision=1,
    )
    db.add(source)
    await db.flush()
    revision = KnowledgeSourceRevision(
        user_id=int(user.id), knowledge_source_id=int(source.id), revision=1,
        content_hash=hashlib.sha256(str(claim_count).encode()).hexdigest(), title_snapshot=source.title_snapshot, status="current",
    )
    db.add(revision)
    await db.flush()
    unit = KnowledgeUnit(
        user_id=int(user.id), source_revision_id=int(revision.id), unit_type="note_body", ordinal=0,
        text="synthetic sparse benchmark evidence", text_hash=hashlib.sha256(b"synthetic sparse benchmark evidence").hexdigest(), locator={},
    )
    db.add(unit)
    await db.flush()

    claims: list[Claim] = []
    for index in range(claim_count):
        if index % 97 == 0:
            statement = f"机会成本要求在项目取舍时考虑放弃的替代方案 {index}"
        elif index % 89 == 0:
            statement = f"A feedback loop can amplify the next cycle {index}"
        elif index % 83 == 0:
            statement = f"服务账号应该遵守最小权限原则 {index}"
        elif index % 79 == 0:
            statement = f"Retrieval practice asks learners to recall from memory {index}"
        else:
            statement = f"普通合成知识条目 {index} 包含稳定的无关背景信息"
        claim = Claim(
            user_id=int(user.id), source_revision_id=int(revision.id), statement=statement,
            fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(), confidence=1.0,
            derivation_type="manual", review_status="confirmed", lifecycle_status="active",
        )
        claims.append(claim)
    db.add_all(claims)
    await db.flush()
    db.add_all([
        ClaimEvidence(
            user_id=int(user.id), claim_id=int(claim.id), knowledge_unit_id=int(unit.id), excerpt="synthetic",
            char_start=0, char_end=1, locator={}, grounding_method="manual", confidence=1.0,
        )
        for claim in claims
    ])
    await db.commit()
    return int(user.id)


async def _measure(index, *, user_id: int, repeats: int) -> dict[str, Any]:
    for query in QUERIES:
        await index.search(user_id=user_id, text=query, top_k=10)
    timings: list[float] = []
    digests: list[list[int]] = []
    tracemalloc.start()
    for _ in range(repeats):
        for query in QUERIES:
            started = time.perf_counter()
            hits = await index.search(user_id=user_id, text=query, top_k=10)
            timings.append((time.perf_counter() - started) * 1000.0)
            digests.append([row.claim_id for row in hits])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "queries": len(timings),
        "mean_ms": round(statistics.mean(timings), 3),
        "p50_ms": round(_percentile(timings, 0.50), 3),
        "p95_ms": round(_percentile(timings, 0.95), 3),
        "peak_tracemalloc_kib": round(peak / 1024.0, 1),
        "digest": digests,
    }


async def run_postgres(*, database_url: str, sizes: list[int], repeats: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for size in sizes:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as db:
                user_id = await _seed(db, claim_count=int(size))
                reference = ReferenceSparseKnowledgeIndex(db)
                postgres = PostgresFtsSparseKnowledgeIndex(db)
                rebuild_started = time.perf_counter()
                rebuild = await postgres.rebuild_user(user_id=user_id)
                await db.commit()
                rebuild_ms = (time.perf_counter() - rebuild_started) * 1000.0
                reference_result = await _measure(reference, user_id=user_id, repeats=repeats)
                postgres_result = await _measure(postgres, user_id=user_id, repeats=repeats)
                parity = reference_result.pop("digest") == postgres_result.pop("digest")
                rows.append({
                    "claims": int(size),
                    "rebuild_ms": round(rebuild_ms, 3),
                    "result_parity": parity,
                    "reference": reference_result,
                    "postgres_fts": postgres_result,
                    "p95_speedup": round(reference_result["p95_ms"] / max(postgres_result["p95_ms"], 0.001), 2),
                    "indexed_claims": int(rebuild.get("indexed_claims") or 0),
                })
        finally:
            await engine.dispose()
    return {"benchmark": "knowledge_sparse_postgres_stage5_v1", "repeats": repeats, "results": rows}


async def run(*, sizes: list[int], repeats: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for size in sizes:
        with tempfile.TemporaryDirectory(prefix=f"mnemox-sparse-{size}-") as temporary:
            engine = create_async_engine(f"sqlite+aiosqlite:///{Path(temporary) / 'bench.db'}")
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as db:
                    user_id = await _seed(db, claim_count=int(size))
                    reference = ReferenceSparseKnowledgeIndex(db)
                    fts = SqliteFts5SparseKnowledgeIndex(db)
                    rebuild_started = time.perf_counter()
                    rebuild = await fts.rebuild_user(user_id=user_id)
                    await db.commit()
                    rebuild_ms = (time.perf_counter() - rebuild_started) * 1000.0
                    reference_result = await _measure(reference, user_id=user_id, repeats=repeats)
                    fts_result = await _measure(fts, user_id=user_id, repeats=repeats)
                    parity = reference_result.pop("digest") == fts_result.pop("digest")
                    rows.append({
                        "claims": int(size),
                        "rebuild_ms": round(rebuild_ms, 3),
                        "result_parity": parity,
                        "reference": reference_result,
                        "sqlite_fts5": fts_result,
                        "p95_speedup": round(reference_result["p95_ms"] / max(fts_result["p95_ms"], 0.001), 2),
                    })
            finally:
                await engine.dispose()
    return {"benchmark": "knowledge_sparse_stage5_v1", "repeats": repeats, "results": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="100,1000,5000")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--postgres-url", default="")
    args = parser.parse_args()
    sizes = [int(value) for value in str(args.sizes).split(",") if str(value).strip()]
    if str(args.postgres_url).strip():
        report = asyncio.run(run_postgres(
            database_url=str(args.postgres_url).strip(),
            sizes=sizes,
            repeats=max(1, int(args.repeats)),
        ))
    else:
        report = asyncio.run(run(sizes=sizes, repeats=max(1, int(args.repeats))))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(row["result_parity"] for row in report["results"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
