#!/usr/bin/env python3
"""Evaluate the deterministic Association V1 baseline on the V2 Stage 0 corpus.

This runner intentionally exercises only the existing SQL Association V1 service.
It creates an ephemeral SQLite database, never initializes an AI provider, and makes
no network calls. The corpus therefore provides a repeatable pre-V2 baseline rather
than an implementation of Claim extraction or Association V2.

Examples:
    python evaluate_knowledge.py --summary-only
    python evaluate_knowledge.py --min-explicit-recall-at-5 0.95 --summary-only
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  Ensure all SQLAlchemy tables are registered.
from app.database import Base
from app.models.concept import Concept, ConceptAlias, ConceptLink
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.note import Note
from app.models.user import User
from app.services.association_service import find_associations
from app.services.association_v2_service import associate as find_associations_v2


FIXTURE = Path(__file__).resolve().parent / "tests" / "fixtures" / "association_v2_eval_cases.json"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _rank_metrics(actual: Iterable[int | str], expected: Iterable[int | str], *, limit: int = 5) -> dict[str, float]:
    actual_keys = list(dict.fromkeys(actual))
    expected_keys = set(expected)
    if not expected_keys:
        return {"recall_at_5": 1.0 if not actual_keys else 0.0, "mrr": 1.0 if not actual_keys else 0.0}
    recall = len(set(actual_keys[:limit]) & expected_keys) / len(expected_keys)
    first = next((rank for rank, key in enumerate(actual_keys, 1) if key in expected_keys), None)
    return {"recall_at_5": recall, "mrr": 1.0 / first if first else 0.0}


def _association_source_keys(associations: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for association in associations:
        evidence_buckets = [association.get("evidence") or {}]
        evidence_buckets.extend(
            prerequisite.get("evidence") or {}
            for prerequisite in association.get("prerequisites") or []
        )
        for evidence in evidence_buckets:
            keys.extend(f"note:{int(item['id'])}" for item in evidence.get("notes") or [])
            keys.extend(
                f"wrong_question:{int(item['id'])}"
                for item in evidence.get("wrong_questions") or []
            )
    return list(dict.fromkeys(keys))


def _summary(case_results: list[dict[str, Any]], scenario: str) -> dict[str, Any]:
    selected = [item for item in case_results if item["scenario"] == scenario]
    positive = [item for item in selected if item["expected_concept_ids"]]
    negative = [item for item in selected if not item["expected_concept_ids"]]
    latencies = [float(item["latency_ms"]) for item in selected]
    return {
        "cases": len(selected),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "recall_at_5": round(
            sum(float(item["concept_metrics"]["recall_at_5"]) for item in positive)
            / max(len(positive), 1),
            4,
        ),
        "mrr": round(
            sum(float(item["concept_metrics"]["mrr"]) for item in positive)
            / max(len(positive), 1),
            4,
        ),
        "source_recall_at_5": round(
            sum(float(item["source_metrics"]["recall_at_5"]) for item in positive)
            / max(len(positive), 1),
            4,
        ),
        "source_mrr": round(
            sum(float(item["source_metrics"]["mrr"]) for item in positive)
            / max(len(positive), 1),
            4,
        ),
        "no_result_rate": round(sum(bool(item["no_result"]) for item in selected) / max(len(selected), 1), 4),
        "expected_no_result_accuracy": round(
            sum(bool(item["no_result"]) for item in negative) / max(len(negative), 1),
            4,
        ),
        "mean_latency_ms": round(sum(latencies) / max(len(latencies), 1), 3),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 3),
    }


async def _seed(db, fixture: dict[str, Any]) -> tuple[dict[int, int], dict[str, int]]:
    for item in fixture["users"]:
        user_id = int(item["id"])
        db.add(
            User(
                id=user_id,
                username=str(item["name"]),
                email=f"stage0-user-{user_id}@example.invalid",
                hashed_password="synthetic-evaluation-only",
                is_active=True,
            )
        )

    source_owners: dict[str, int] = {}
    for source in fixture["evidence_sources"]:
        source_key = str(source["key"])
        source_owners[source_key] = int(source["user_id"])
        if source["source_type"] != "note":
            raise ValueError(f"Association V1 Stage 0 only supports note evidence, got {source_key}")
        db.add(
            Note(
                id=int(source["id"]),
                user_id=int(source["user_id"]),
                title=str(source["title"]),
                content=str(source["content"]),
                tags="[]",
                note_type="general",
            )
        )

    concept_owners: dict[int, int] = {}
    for item in fixture["concepts"]:
        concept_id = int(item["id"])
        user_id = int(item["user_id"])
        concept_owners[concept_id] = user_id
        name = str(item["name"])
        db.add(
            Concept(
                id=concept_id,
                user_id=user_id,
                name=name,
                name_normalized=name.lower(),
                description="Stage 0 synthetic baseline concept",
                source="manual",
                review_status="confirmed",
            )
        )
        for alias_index, alias in enumerate(item.get("aliases") or [], 1):
            db.add(
                ConceptAlias(
                    id=(concept_id * 10) + alias_index,
                    user_id=user_id,
                    concept_id=concept_id,
                    alias=str(alias),
                    alias_normalized=str(alias).lower(),
                    source="stage0_fixture",
                )
            )
        for source_key in item.get("evidence_source_keys") or []:
            source = next(row for row in fixture["evidence_sources"] if row["key"] == source_key)
            if int(source["user_id"]) != user_id:
                raise ValueError(f"Cross-user fixture link is forbidden: concept {concept_id} -> {source_key}")
            db.add(
                ConceptLink(
                    user_id=user_id,
                    concept_id=concept_id,
                    target_type="note",
                    target_id=int(source["id"]),
                    link_type="explains",
                )
            )
    await db.commit()
    return concept_owners, source_owners


async def _evaluate_case(
    db,
    case: dict[str, Any],
    *,
    concept_owners: dict[int, int],
    source_owners: dict[str, int],
) -> dict[str, Any]:
    started = time.perf_counter()
    associations = await find_associations(
        db,
        int(case["user_id"]),
        str(case["query"]),
        limit=10,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    actual_concepts = [int(item["concept_id"]) for item in associations]
    actual_sources = _association_source_keys(associations)
    forbidden_users = {int(value) for value in case.get("forbidden_user_ids") or []}
    forbidden_concepts = [
        concept_id for concept_id in actual_concepts if concept_owners.get(concept_id) in forbidden_users
    ]
    forbidden_sources = [
        source_key for source_key in actual_sources if source_owners.get(source_key) in forbidden_users
    ]
    return {
        "id": str(case["id"]),
        "scenario": str(case["scenario"]),
        "language": str(case["language"]),
        "expected_concept_ids": [int(value) for value in case["expected_concept_ids"]],
        "actual_concept_ids": actual_concepts,
        "expected_related_source_keys": [str(value) for value in case["expected_related_source_keys"]],
        "actual_related_source_keys": actual_sources,
        "concept_metrics": _rank_metrics(actual_concepts, case["expected_concept_ids"]),
        "source_metrics": _rank_metrics(actual_sources, case["expected_related_source_keys"]),
        "no_result": not associations,
        "latency_ms": round(latency_ms, 3),
        "forbidden_concept_ids": forbidden_concepts,
        "forbidden_source_keys": forbidden_sources,
    }


async def _seed_v2_graph(db, fixture: dict[str, Any]) -> None:
    """Seed grounded Claim paths represented by the corpus annotations."""
    next_source_id = 1
    source_claims: dict[str, Claim] = {}
    for source in fixture["evidence_sources"]:
        content = str(source["content"])
        canonical = KnowledgeSource(
            id=next_source_id,
            user_id=int(source["user_id"]),
            source_type=str(source["source_type"]),
            source_record_id=int(source["id"]),
            source_key=str(source["key"]),
            title_snapshot=str(source["title"]),
            status="active",
            current_revision=1,
        )
        next_source_id += 1
        db.add(canonical)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=int(source["user_id"]), knowledge_source_id=int(canonical.id), revision=1,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            title_snapshot=str(source["title"]), status="current",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=int(source["user_id"]), source_revision_id=int(revision.id), unit_type="note_body",
            ordinal=0, text=content, text_hash=hashlib.sha256(content.encode()).hexdigest(), locator={},
        )
        claim = Claim(
            user_id=int(source["user_id"]), source_revision_id=int(revision.id), statement=content,
            fingerprint=hashlib.sha256(content.casefold().encode()).hexdigest(), claim_kind="observation",
            confidence=1.0, derivation_type="manual", review_status="confirmed", lifecycle_status="active",
        )
        db.add_all((unit, claim))
        await db.flush()
        db.add(ClaimEvidence(
            user_id=int(source["user_id"]), claim_id=int(claim.id), knowledge_unit_id=int(unit.id),
            excerpt=content, char_start=0, char_end=len(content), locator={}, grounding_method="manual", confidence=1.0,
        ))
        source_claims[str(source["key"])] = claim

    for concept in fixture["concepts"]:
        for source_key in concept.get("evidence_source_keys") or []:
            claim = source_claims[str(source_key)]
            db.add(ClaimConceptLink(
                user_id=int(concept["user_id"]), claim_id=int(claim.id), concept_id=int(concept["id"]),
                relation_type="about", mention_text=str(concept["name"]), confidence=1.0,
                derivation_type="manual", review_status="confirmed",
            ))

    await db.commit()


async def _seed_v2_anchor(db, case: dict[str, Any]) -> KnowledgeSource:
    """Create one reviewed query anchor for a single evaluation case.

    Anchors are intentionally scoped to one case. Keeping all synthetic query
    anchors active at once lets one test question become another question's
    retrieval result, which inflates recall and creates false lifecycle hits.
    """
    text_value = str(case["query"])
    _, record_id = str(case["anchor_source_key"]).split(":", 1)
    canonical = KnowledgeSource(
        user_id=int(case["user_id"]), source_type="material",
        source_record_id=int(record_id), source_key=str(case["anchor_source_key"]),
        title_snapshot=f"Evaluation anchor {case['id']}", status="active", current_revision=1,
    )
    db.add(canonical)
    await db.flush()
    revision = KnowledgeSourceRevision(
        user_id=int(case["user_id"]), knowledge_source_id=int(canonical.id), revision=1,
        content_hash=hashlib.sha256(text_value.encode()).hexdigest(), title_snapshot=canonical.title_snapshot,
        status="current",
    )
    db.add(revision)
    await db.flush()
    unit = KnowledgeUnit(
        user_id=int(case["user_id"]), source_revision_id=int(revision.id), unit_type="chunk",
        ordinal=0, text=text_value, text_hash=hashlib.sha256(text_value.encode()).hexdigest(), locator={},
    )
    claim = Claim(
        user_id=int(case["user_id"]), source_revision_id=int(revision.id), statement=text_value,
        fingerprint=hashlib.sha256(text_value.casefold().encode()).hexdigest(), claim_kind="observation",
        confidence=1.0, derivation_type="manual", review_status="confirmed", lifecycle_status="active",
    )
    db.add_all((unit, claim))
    await db.flush()
    db.add(ClaimEvidence(
        user_id=int(case["user_id"]), claim_id=int(claim.id), knowledge_unit_id=int(unit.id),
        excerpt=text_value, char_start=0, char_end=len(text_value), locator={}, grounding_method="manual", confidence=1.0,
    ))
    for concept_id in case["expected_concept_ids"]:
        db.add(ClaimConceptLink(
            user_id=int(case["user_id"]), claim_id=int(claim.id), concept_id=int(concept_id),
            relation_type="about", mention_text="fixture-reviewed-anchor", confidence=1.0,
            derivation_type="manual", review_status="confirmed",
        ))
    await db.commit()
    return canonical


async def _retire_v2_anchor(db, source: KnowledgeSource) -> None:
    """Tombstone the synthetic query anchor so it cannot contaminate later cases."""
    source.status = "deleted"
    revisions = list((await db.scalars(select(KnowledgeSourceRevision).where(
        KnowledgeSourceRevision.knowledge_source_id == int(source.id)
    ))).all())
    for revision in revisions:
        revision.status = "deleted"
    revision_ids = [int(row.id) for row in revisions]
    if revision_ids:
        claims = list((await db.scalars(select(Claim).where(Claim.source_revision_id.in_(revision_ids)))).all())
        for claim in claims:
            claim.lifecycle_status = "deleted"
    await db.commit()


async def _evaluate_v2_case(db, case: dict[str, Any], *, concept_owners: dict[int, int], source_owners: dict[str, int]) -> dict[str, Any]:
    started = time.perf_counter()
    _, source_id = str(case["anchor_source_key"]).split(":", 1)
    payload = await find_associations_v2(
        db, user_id=int(case["user_id"]), text=str(case["query"]), source_type="material",
        source_id=int(source_id), limit=5,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    associations = payload["associations"]
    actual_concepts = list(dict.fromkeys(
        int(concept["id"]) for item in associations for concept in item["anchor"]["concepts"]
    ))
    actual_sources = list(dict.fromkeys(
        f"{item['related']['source_type']}:{int(item['related']['source_id'])}" for item in associations
    ))
    forbidden_users = {int(value) for value in case.get("forbidden_user_ids") or []}
    unsupported = sum(
        not item["evidence"]["anchor"] or not item["evidence"]["related"]
        for item in associations
    )
    return {
        "id": str(case["id"]), "scenario": str(case["scenario"]), "language": str(case["language"]),
        "expected_concept_ids": [int(value) for value in case["expected_concept_ids"]],
        "actual_concept_ids": actual_concepts,
        "expected_related_source_keys": [str(value) for value in case["expected_related_source_keys"]],
        "actual_related_source_keys": actual_sources,
        "concept_metrics": _rank_metrics(actual_concepts, case["expected_concept_ids"]),
        "source_metrics": _rank_metrics(actual_sources, case["expected_related_source_keys"]),
        "no_result": not associations, "latency_ms": round(latency_ms, 3),
        "forbidden_concept_ids": [value for value in actual_concepts if concept_owners.get(value) in forbidden_users],
        "forbidden_source_keys": [value for value in actual_sources if source_owners.get(value) in forbidden_users],
        "unsupported_results": unsupported,
    }


async def run_stage4_evaluation() -> dict[str, Any]:
    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    with tempfile.TemporaryDirectory(prefix="mnemox-knowledge-stage4-") as temporary:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(temporary) / 'association-v2.sqlite3'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as db:
                concept_owners, source_owners = await _seed(db, fixture)
                await _seed_v2_graph(db, fixture)
                regular = [case for case in fixture["cases"] if case.get("lifecycle_phase") != "after_delete"]
                lifecycle = [case for case in fixture["cases"] if case.get("lifecycle_phase") == "after_delete"]
                results: list[dict[str, Any]] = []
                for case in regular:
                    anchor = await _seed_v2_anchor(db, case)
                    try:
                        results.append(await _evaluate_v2_case(
                            db, case, concept_owners=concept_owners, source_owners=source_owners
                        ))
                    finally:
                        await _retire_v2_anchor(db, anchor)

                deleted_residual = 0
                for case in lifecycle:
                    source = await db.scalar(select(KnowledgeSource).where(KnowledgeSource.source_key == str(case["delete_source_key"])))
                    source.status = "deleted"
                    revisions = list((await db.scalars(select(KnowledgeSourceRevision).where(KnowledgeSourceRevision.knowledge_source_id == int(source.id)))).all())
                    for revision in revisions:
                        revision.status = "deleted"
                    claims = list((await db.scalars(select(Claim).where(Claim.source_revision_id.in_([int(row.id) for row in revisions])))).all())
                    for claim in claims:
                        claim.lifecycle_status = "deleted"
                    await db.commit()
                    anchor = await _seed_v2_anchor(db, case)
                    try:
                        result = await _evaluate_v2_case(db, case, concept_owners=concept_owners, source_owners=source_owners)
                    finally:
                        await _retire_v2_anchor(db, anchor)
                    deleted_residual += len(result["actual_related_source_keys"])
                    results.append(result)
                digest_rows = [{"id": row["id"], "concepts": row["actual_concept_ids"], "sources": row["actual_related_source_keys"]} for row in sorted(results, key=lambda value: value["id"])]
                return {
                    "baseline": "association_v2_sql_graph_feature_v1", "fixture": str(FIXTURE.relative_to(Path(__file__).resolve().parent)),
                    "fixture_version": fixture["version"], "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                    "questions": len(results), "external_model_calls": 0,
                    "deterministic_result_sha256": hashlib.sha256(json.dumps(digest_rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "results": {"explicit": _summary(results, "explicit"), "implicit": _summary(results, "implicit")},
                    "lifecycle_probes": {
                        "user_isolation_violations": sum(len(row["forbidden_concept_ids"]) + len(row["forbidden_source_keys"]) for row in results),
                        "deleted_source_residual_hits": deleted_residual,
                        "unsupported_display_count": sum(row["unsupported_results"] for row in results),
                        "negative_false_positive_count": sum(not row["no_result"] for row in results if not row["expected_concept_ids"]),
                    },
                    "per_case": results,
                }
        finally:
            await engine.dispose()


async def run_evaluation() -> dict[str, Any]:
    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    with tempfile.TemporaryDirectory(prefix="mnemox-knowledge-stage0-") as temporary:
        database_path = Path(temporary) / "association-v1.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as db:
                concept_owners, source_owners = await _seed(db, fixture)
                # Keep connection setup and SQL compilation out of the measured
                # steady-state case latency without mutating fixture state.
                await find_associations(db, 1, "stage zero warmup with no matching term", limit=1)
                regular_cases = [
                    case for case in fixture["cases"] if case.get("lifecycle_phase") != "after_delete"
                ]
                lifecycle_cases = [
                    case for case in fixture["cases"] if case.get("lifecycle_phase") == "after_delete"
                ]
                case_results = [
                    await _evaluate_case(
                        db,
                        case,
                        concept_owners=concept_owners,
                        source_owners=source_owners,
                    )
                    for case in regular_cases
                ]

                deleted_source_residual_hits = 0
                for case in lifecycle_cases:
                    source_key = str(case["delete_source_key"])
                    source = next(row for row in fixture["evidence_sources"] if row["key"] == source_key)
                    source_id = int(source["id"])
                    user_id = int(source["user_id"])
                    await db.execute(
                        delete(ConceptLink).where(
                            ConceptLink.user_id == user_id,
                            ConceptLink.target_type == "note",
                            ConceptLink.target_id == source_id,
                        )
                    )
                    note = await db.scalar(select(Note).where(Note.id == source_id, Note.user_id == user_id))
                    if note is not None:
                        await db.delete(note)
                    await db.commit()
                    result = await _evaluate_case(
                        db,
                        case,
                        concept_owners=concept_owners,
                        source_owners=source_owners,
                    )
                    deleted_source_residual_hits += len(result["actual_related_source_keys"])
                    deleted_source_residual_hits += len(result["actual_concept_ids"])
                    case_results.append(result)

                deterministic_rows = [
                    {
                        "id": item["id"],
                        "actual_concept_ids": item["actual_concept_ids"],
                        "actual_related_source_keys": item["actual_related_source_keys"],
                    }
                    for item in sorted(case_results, key=lambda row: row["id"])
                ]
                deterministic_digest = hashlib.sha256(
                    json.dumps(deterministic_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                isolation_violations = sum(
                    len(item["forbidden_concept_ids"]) + len(item["forbidden_source_keys"])
                    for item in case_results
                )
                return {
                    "baseline": "association_v1_sql_exact_alias",
                    "fixture": str(FIXTURE.relative_to(Path(__file__).resolve().parent)),
                    "fixture_version": fixture["version"],
                    "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                    "questions": len(case_results),
                    "external_model_calls": 0,
                    "deterministic_result_sha256": deterministic_digest,
                    "results": {
                        "explicit": _summary(case_results, "explicit"),
                        "implicit": _summary(case_results, "implicit"),
                    },
                    "lifecycle_probes": {
                        "user_isolation_violations": isolation_violations,
                        "deleted_source_residual_hits": deleted_source_residual_hits,
                    },
                    "per_case": case_results,
                }
        finally:
            await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-explicit-recall-at-5", type=float, default=0.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--mode", choices=("v1", "v2", "compare"), default="v1")
    args = parser.parse_args()

    if args.mode == "v1":
        report = asyncio.run(run_evaluation())
    elif args.mode == "v2":
        report = asyncio.run(run_stage4_evaluation())
    else:
        v1 = asyncio.run(run_evaluation())
        v2 = asyncio.run(run_stage4_evaluation())
        report = {
            "mode": "compare", "v1": v1, "v2": v2,
            "recall_at_5_delta": {
                scenario: round(v2["results"][scenario]["recall_at_5"] - v1["results"][scenario]["recall_at_5"], 4)
                for scenario in ("explicit", "implicit")
            },
        }
    if args.summary_only:
        report.pop("per_case", None)
        for value in (report.get("v1"), report.get("v2")):
            if isinstance(value, dict):
                value.pop("per_case", None)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(output + "\n", encoding="utf-8")
    print(output)
    gate_report = report.get("v2") or report
    if gate_report["results"]["explicit"]["recall_at_5"] < args.min_explicit_recall_at_5:
        return 2
    if gate_report["lifecycle_probes"]["user_isolation_violations"]:
        return 3
    if gate_report["lifecycle_probes"]["deleted_source_residual_hits"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
