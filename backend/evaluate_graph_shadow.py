"""Stage 6 SQL vs Neo4j fixed-path Shadow benchmark.

The benchmark creates only synthetic data in a temporary SQLite canonical DB and
uses an explicitly provided disposable Neo4j database. It never changes product
routing and never invokes an LLM.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
from app.services.graph_store.neo4j_store import Neo4jAsyncExecutor, Neo4jGraphStore
from app.services.graph_store.sql_store import SqlGraphStore


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def _latency(values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": round(statistics.mean(values), 3) if values else 0.0,
        "p50_ms": round(_percentile(values, 0.50), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
    }


def _id_signature(rows) -> tuple[int, ...]:
    return tuple(sorted(int(row.object_id) for row in rows))


def _path_signature(rows) -> tuple[tuple[int, str, int], ...]:
    return tuple(sorted((int(row.object_id), str(row.path_type), int(row.depth)) for row in rows))


def _score_signature(rows) -> tuple[tuple[int, str, int, float], ...]:
    return tuple(sorted(
        (int(row.object_id), str(row.path_type), int(row.depth), round(float(row.confidence), 6))
        for row in rows
    ))


def _compose_hits(shared_rows, direct_rows, *, limit: int = 50):
    merged = {int(row.object_id): row for row in shared_rows}
    merged.update({int(row.object_id): row for row in direct_rows})
    return sorted(
        merged.values(),
        key=lambda row: (-float(row.confidence), int(row.depth), int(row.object_id)),
    )[: int(limit)]


async def _seed(db, *, claim_count: int) -> tuple[int, tuple[int, ...], int]:
    owner = User(
        username=f"stage6-bench-{claim_count}",
        email=f"stage6-bench-{claim_count}@example.test",
        hashed_password="hash",
    )
    stranger = User(
        username=f"stage6-stranger-{claim_count}",
        email=f"stage6-stranger-{claim_count}@example.test",
        hashed_password="hash",
    )
    db.add_all((owner, stranger))
    await db.flush()

    source = KnowledgeSource(
        user_id=int(owner.id),
        source_type="note",
        source_record_id=1,
        source_key="note:1",
        title_snapshot="Synthetic Stage 6 graph",
        status="active",
        current_revision=1,
    )
    db.add(source)
    await db.flush()
    revision = KnowledgeSourceRevision(
        user_id=int(owner.id),
        knowledge_source_id=int(source.id),
        revision=1,
        content_hash=hashlib.sha256(str(claim_count).encode()).hexdigest(),
        title_snapshot=source.title_snapshot,
        status="current",
    )
    db.add(revision)
    await db.flush()
    unit = KnowledgeUnit(
        user_id=int(owner.id),
        source_revision_id=int(revision.id),
        unit_type="note_body",
        ordinal=0,
        text="synthetic evidence",
        text_hash=hashlib.sha256(b"synthetic evidence").hexdigest(),
        locator={},
    )
    db.add(unit)
    await db.flush()

    concept_count = max(5, min(100, claim_count // 10 or 5))
    concepts = [
        Concept(
            user_id=int(owner.id),
            name=f"Concept {index}",
            name_normalized=f"concept {index}",
            source="manual",
            review_status="confirmed",
        )
        for index in range(concept_count)
    ]
    db.add_all(concepts)
    await db.flush()

    claims: list[Claim] = []
    for index in range(claim_count):
        statement = f"Synthetic confirmed graph claim {index}"
        claims.append(
            Claim(
                user_id=int(owner.id),
                source_revision_id=int(revision.id),
                statement=statement,
                fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(),
                confidence=0.80 + (index % 10) * 0.01,
                derivation_type="manual",
                review_status="confirmed",
                lifecycle_status="active",
            )
        )
    db.add_all(claims)
    await db.flush()
    db.add_all([
        ClaimEvidence(
            user_id=int(owner.id),
            claim_id=int(claim.id),
            knowledge_unit_id=int(unit.id),
            excerpt="synthetic",
            char_start=0,
            char_end=1,
            locator={},
            grounding_method="manual",
            confidence=1.0,
        )
        for claim in claims
    ])
    claim_concept_types = ("about", "uses", "applies_to", "exemplifies")
    db.add_all([
        ClaimConceptLink(
            user_id=int(owner.id),
            claim_id=int(claim.id),
            concept_id=int(concepts[index % concept_count].id),
            relation_type=claim_concept_types[index % len(claim_concept_types)],
            mention_text=f"concept {index % concept_count}",
            confidence=0.90 + (index % 5) * 0.01,
            derivation_type="manual",
            review_status="confirmed",
        )
        for index, claim in enumerate(claims)
    ])
    claim_relation_types = ("supports", "contradicts", "refines", "exemplifies", "analogous_to")
    db.add_all([
        ClaimRelation(
            user_id=int(owner.id),
            from_claim_id=int(claims[index].id),
            to_claim_id=int(claims[index + 1].id),
            relation_type=claim_relation_types[index % len(claim_relation_types)],
            confidence=0.85 + (index % 10) * 0.01,
            derivation_type="manual",
            review_status="confirmed",
            rationale="synthetic",
        )
        for index in range(max(0, claim_count - 1))
    ])

    foreign_source = KnowledgeSource(
        user_id=int(stranger.id), source_type="note", source_record_id=2,
        source_key="note:2", title_snapshot="Foreign", status="active", current_revision=1,
    )
    db.add(foreign_source)
    await db.flush()
    foreign_revision = KnowledgeSourceRevision(
        user_id=int(stranger.id), knowledge_source_id=int(foreign_source.id), revision=1,
        content_hash=hashlib.sha256(b"foreign").hexdigest(), title_snapshot="Foreign", status="current",
    )
    db.add(foreign_revision)
    await db.flush()
    foreign_unit = KnowledgeUnit(
        user_id=int(stranger.id), source_revision_id=int(foreign_revision.id), unit_type="note_body",
        ordinal=0, text="foreign", text_hash=hashlib.sha256(b"foreign").hexdigest(), locator={},
    )
    foreign_claim = Claim(
        user_id=int(stranger.id), source_revision_id=int(foreign_revision.id), statement="foreign sentinel",
        fingerprint=hashlib.sha256(b"foreign sentinel").hexdigest(), confidence=1.0,
        derivation_type="manual", review_status="confirmed", lifecycle_status="active",
    )
    db.add_all((foreign_unit, foreign_claim))
    await db.flush()
    db.add(ClaimEvidence(
        user_id=int(stranger.id), claim_id=int(foreign_claim.id), knowledge_unit_id=int(foreign_unit.id),
        excerpt="foreign", char_start=0, char_end=1, locator={}, grounding_method="manual", confidence=1.0,
    ))
    await db.commit()
    return int(owner.id), tuple(int(row.id) for row in claims), int(foreign_claim.id)


async def _benchmark_case(
    *,
    claim_count: int,
    query_count: int,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"mnemox-stage6-{claim_count}-") as temporary:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(temporary) / 'canonical.db'}")
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        executor = Neo4jAsyncExecutor(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
        )
        try:
            await executor.verify_connectivity()
            async with sessions() as db:
                user_id, claim_ids, foreign_claim_id = await _seed(db, claim_count=claim_count)
                sql_store = SqlGraphStore(db)
                neo_store = Neo4jGraphStore(db, executor=executor)
                rebuild_started = time.perf_counter()
                rebuild = await neo_store.rebuild_user(user_id=user_id)
                rebuild_ms = (time.perf_counter() - rebuild_started) * 1000.0

                step = max(1, len(claim_ids) // max(1, query_count))
                anchors = claim_ids[::step][: max(1, query_count)]
                probes = (
                    ("direct", ("direct_claim_relations",), 3),
                    ("shared", ("shared_concept_claims",), 1),
                    ("combined", ("direct_claim_relations", "shared_concept_claims"), 3),
                )
                probe_reports: list[dict[str, Any]] = []
                cross_user_hits = 0
                for name, patterns, depth in probes:
                    sql_times: list[float] = []
                    neo_times: list[float] = []
                    id_matches = 0
                    path_matches = 0
                    score_matches = 0
                    # Exclude driver/planner cold start from steady-state p95.
                    warm_anchor = anchors[0]
                    await sql_store.expand_claims(
                        user_id=user_id, claim_ids=(warm_anchor,), patterns=patterns, depth=depth, limit=50
                    )
                    await neo_store.expand_claims(
                        user_id=user_id, claim_ids=(warm_anchor,), patterns=patterns, depth=depth, limit=50
                    )
                    for anchor in anchors:
                        started = time.perf_counter()
                        sql_hits = await sql_store.expand_claims(
                            user_id=user_id, claim_ids=(anchor,), patterns=patterns, depth=depth, limit=50
                        )
                        sql_times.append((time.perf_counter() - started) * 1000.0)
                        started = time.perf_counter()
                        neo_hits = await neo_store.expand_claims(
                            user_id=user_id, claim_ids=(anchor,), patterns=patterns, depth=depth, limit=50
                        )
                        neo_times.append((time.perf_counter() - started) * 1000.0)
                        id_matches += int(_id_signature(sql_hits) == _id_signature(neo_hits))
                        path_matches += int(_path_signature(sql_hits) == _path_signature(neo_hits))
                        score_matches += int(_score_signature(sql_hits) == _score_signature(neo_hits))
                        cross_user_hits += sum(
                            1 for row in neo_hits if int(row.object_id) == int(foreign_claim_id)
                        )
                    probe_reports.append({
                        "probe": name,
                        "queries": len(anchors),
                        "id_set_match_rate": round(id_matches / max(1, len(anchors)), 4),
                        "path_signature_match_rate": round(path_matches / max(1, len(anchors)), 4),
                        "score_signature_match_rate": round(score_matches / max(1, len(anchors)), 4),
                        "sql": _latency(sql_times),
                        "neo4j": _latency(neo_times),
                        "p95_speed_ratio_sql_over_neo4j": round(
                            _latency(sql_times)["p95_ms"] / max(_latency(neo_times)["p95_ms"], 0.001), 3
                        ),
                    })

                composition_anchor = anchors[-1]
                sql_shared = await sql_store.expand_claims(
                    user_id=user_id, claim_ids=(composition_anchor,), patterns=("shared_concept_claims",), depth=1, limit=50
                )
                sql_direct = await sql_store.expand_claims(
                    user_id=user_id, claim_ids=(composition_anchor,), patterns=("direct_claim_relations",), depth=3, limit=50
                )
                sql_combined = await sql_store.expand_claims(
                    user_id=user_id, claim_ids=(composition_anchor,), patterns=("direct_claim_relations", "shared_concept_claims"), depth=3, limit=50
                )
                neo_shared = await neo_store.expand_claims(
                    user_id=user_id, claim_ids=(composition_anchor,), patterns=("shared_concept_claims",), depth=1, limit=50
                )
                neo_direct = await neo_store.expand_claims(
                    user_id=user_id, claim_ids=(composition_anchor,), patterns=("direct_claim_relations",), depth=3, limit=50
                )
                neo_combined = await neo_store.expand_claims(
                    user_id=user_id, claim_ids=(composition_anchor,), patterns=("direct_claim_relations", "shared_concept_claims"), depth=3, limit=50
                )
                sql_manual = _compose_hits(sql_shared, sql_direct)
                neo_manual = _compose_hits(neo_shared, neo_direct)
                composition_probe = {
                    "sql_combined_matches_manual": _score_signature(sql_combined) == _score_signature(sql_manual),
                    "neo4j_combined_matches_manual": _score_signature(neo_combined) == _score_signature(neo_manual),
                    "manual_sql_matches_neo4j": _score_signature(sql_manual) == _score_signature(neo_manual),
                    "sql_combined_count": len(sql_combined),
                    "neo4j_combined_count": len(neo_combined),
                    "sql_manual_count": len(sql_manual),
                    "neo4j_manual_count": len(neo_manual),
                }

                raw_property_rows = await executor.execute(
                    "MATCH (n {user_id:$user_id}) UNWIND keys(n) AS key RETURN DISTINCT key",
                    {"user_id": user_id},
                )
                properties = {str(row["key"]) for row in raw_property_rows}
                forbidden_properties = properties & {"statement", "text", "excerpt", "title", "content"}
                return {
                    "claims": int(claim_count),
                    "queries_per_probe": len(anchors),
                    "rebuild_ms": round(rebuild_ms, 3),
                    "projection": rebuild,
                    "cross_user_hits": int(cross_user_hits),
                    "forbidden_raw_properties": sorted(forbidden_properties),
                    "composition_probe": composition_probe,
                    "probes": probe_reports,
                }
        finally:
            await executor.close()
            await engine.dispose()


async def run(args) -> dict[str, Any]:
    results = []
    for value in str(args.sizes).split(","):
        value = value.strip()
        if not value:
            continue
        results.append(await _benchmark_case(
            claim_count=int(value),
            query_count=max(1, int(args.queries)),
            neo4j_uri=str(args.neo4j_uri),
            neo4j_user=str(args.neo4j_user),
            neo4j_password=str(args.neo4j_password),
            neo4j_database=str(args.neo4j_database),
        ))
    return {
        "benchmark": "mnemox_stage6_neo4j_shadow_v1",
        "results": results,
        "go_gate_snapshot": {
            "all_id_sets_match": all(
                probe["id_set_match_rate"] == 1.0
                for row in results for probe in row["probes"]
            ),
            "all_paths_match": all(
                probe["path_signature_match_rate"] == 1.0
                for row in results for probe in row["probes"]
            ),
            "all_scores_match": all(
                probe["score_signature_match_rate"] == 1.0
                for row in results for probe in row["probes"]
            ),
            "cross_user_hits": sum(int(row["cross_user_hits"]) for row in results),
            "raw_property_violations": sum(len(row["forbidden_raw_properties"]) for row in results),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--sizes", default="100,1000")
    parser.add_argument("--queries", type=int, default=12)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    gate = report["go_gate_snapshot"]
    return 0 if (
        gate["all_id_sets_match"]
        and gate["all_paths_match"]
        and gate["all_scores_match"]
        and gate["cross_user_hits"] == 0
        and gate["raw_property_violations"] == 0
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
