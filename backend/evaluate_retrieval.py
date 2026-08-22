#!/usr/bin/env python3
"""Run the deterministic retrieval quality corpus without external model calls.

Examples:
    python evaluate_retrieval.py --backend hybrid --min-recall-at-5 0.75
    python -m pip install -r requirements-spike.txt
    python evaluate_retrieval.py --backend all --include-qdrant
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import chromadb
from llama_index.core.node_parser import SentenceSplitter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.ai.rag_service import RAGService
from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.material import Material
from app.models.note import Note
from app.models.user import User
from app.services.material_retrieval_backend import (
    ChromaMaterialRetrievalBackend,
    HybridMaterialRetrievalBackend,
    KeywordMaterialRetrievalBackend,
    _tokenize,
)
from app.services.retrieval_projection_service import RetrievalProjectionService
from app.services.retrieval_router import RetrievalRouter

FIXTURE = Path(__file__).resolve().parent / "tests" / "fixtures" / "retrieval_eval_cases.json"
DIMENSION = 64


class DeterministicEmbedding:
    """Stable local hashed token embeddings shared by every compared backend."""

    def get_text_embedding(self, text: str) -> list[float]:
        values = [0.0] * DIMENSION
        for token, count in Counter(_tokenize(text)).items():
            digest = hashlib.blake2s(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % DIMENSION
            sign = 1.0 if digest[4] % 2 else -1.0
            values[bucket] += sign * (1.0 + math.log(float(count)))
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def get_text_embedding_batch(self, texts: list[str], **_kwargs: Any) -> list[list[float]]:
        return [self.get_text_embedding(text) for text in texts]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _metrics(keys: list[str], relevance: dict[str, int]) -> dict[str, float]:
    if not relevance:
        return {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr": 1.0, "ndcg_at_10": 1.0}
    deduplicated = list(dict.fromkeys(keys))
    relevant = set(relevance)
    recalls = {
        f"recall_at_{limit}": len(set(deduplicated[:limit]) & relevant) / len(relevant)
        for limit in (5, 10)
    }
    first = next((index for index, key in enumerate(deduplicated, 1) if key in relevant), None)
    dcg = sum(
        (2 ** relevance.get(key, 0) - 1) / math.log2(index + 1)
        for index, key in enumerate(deduplicated[:10], 1)
    )
    ideal = sorted(relevance.values(), reverse=True)[:10]
    ideal_dcg = sum((2 ** grade - 1) / math.log2(index + 1) for index, grade in enumerate(ideal, 1))
    return {
        **recalls,
        "mrr": 1.0 / first if first else 0.0,
        "ndcg_at_10": dcg / ideal_dcg if ideal_dcg else 0.0,
    }


async def _seed(db, fixture: dict[str, Any], rag: RAGService) -> dict[str, int]:
    db.add_all(
        [
            User(id=1, username="retrieval-owner", email="owner@retrieval.test", hashed_password="hash"),
            User(id=2, username="retrieval-outsider", email="outsider@retrieval.test", hashed_password="hash"),
        ]
    )
    await db.flush()
    owners: dict[str, int] = {}
    for item in fixture["materials"]:
        content = str(item["content"])
        db.add(
            Material(
                id=int(item["id"]),
                user_id=int(item["user_id"]),
                title=str(item["title"]),
                content=content,
                content_hash=hashlib.sha256(content.strip().encode("utf-8")).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
        )
        owners[f"material:{item['id']}"] = int(item["user_id"])
    for item in fixture["notes"]:
        db.add(
            Note(
                id=int(item["id"]),
                user_id=int(item["user_id"]),
                title=str(item["title"]),
                content=str(item["content"]),
                tags=json.dumps(item.get("tags", []), ensure_ascii=False),
                note_type="general",
            )
        )
        owners[f"note:{item['id']}"] = int(item["user_id"])
    for item in fixture["concepts"]:
        db.add(
            Concept(
                id=int(item["id"]),
                user_id=int(item["user_id"]),
                name=str(item["name"]),
                name_normalized=str(item["name"]).lower(),
                description=str(item["description"]),
                source="manual",
            )
        )
        owners[f"concept:{item['id']}"] = int(item["user_id"])
    await db.commit()

    service = RetrievalProjectionService(db, rag=rag)
    materials = list((await db.scalars(select(Material).order_by(Material.id))).all())
    for material in materials:
        result = await service.ingest(material, user_id=int(material.user_id))
        if result["status"] != "ready":
            raise RuntimeError(f"Fixture indexing failed for material {material.id}: {result}")
    return owners


def _ephemeral_rag() -> RAGService:
    rag = RAGService()
    client = chromadb.EphemeralClient()
    collection_name = f"mnemox_eval_{time.monotonic_ns()}"
    rag._chroma_client = client
    rag._collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    rag._embed_model = DeterministicEmbedding()
    rag._splitter = SentenceSplitter(
        chunk_size=int(settings.RAG_CHUNK_SIZE),
        chunk_overlap=int(settings.RAG_CHUNK_OVERLAP),
    )
    rag._current_model = "deterministic-local-hash-v1"
    rag._current_base_url = "local://deterministic"
    rag._chunk_size = int(settings.RAG_CHUNK_SIZE)
    rag._chunk_overlap = int(settings.RAG_CHUNK_OVERLAP)
    rag._similarity_threshold = 0.0
    rag._initialized = True
    return rag


async def _evaluate_backend(
    name: str,
    backend,
    db,
    fixture: dict[str, Any],
    owners: dict[str, int],
) -> dict[str, Any]:
    router = RetrievalRouter(db, material_backend=backend)
    # Exclude connection/query compilation from the measured steady-state paths.
    await router.search("warmup RRF", user_id=1, source_types=("material",), top_k=10)
    results = []
    latency_ms = []
    forbidden_hits = 0
    compatibility_passed = True
    material_hits = 0

    for case in fixture["cases"]:
        start = time.perf_counter()
        hits = await router.search(
            str(case["query"]),
            user_id=int(case["user_id"]),
            source_types=tuple(case["source_types"]),
            top_k=10,
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        latency_ms.append(elapsed)
        keys = [f"{hit.source_type}:{hit.source_id}" for hit in hits]
        leaked = [
            key for key in keys
            if owners.get(key) in {int(value) for value in case.get("forbidden_user_ids", [])}
        ]
        forbidden_hits += len(leaked)
        expected_material_ids = {int(value) for value in case.get("expected_material_ids", [])}
        if expected_material_ids:
            material_hits += int(any(
                hit.source_type == "material" and int(hit.source_id) in expected_material_ids
                for hit in hits[:5]
            ))
        if case.get("compatibility_only"):
            compatibility_passed = compatibility_passed and not leaked
            continue
        values = _metrics(keys, {str(key): int(value) for key, value in case["relevance"].items()})
        results.append(
            {
                "id": case["id"],
                "top_sources": keys[:5],
                "latency_ms": round(elapsed, 3),
                "forbidden_hits": leaked,
                **{key: round(value, 4) for key, value in values.items()},
            }
        )

    expected_material_case_count = sum(
        bool(case.get("expected_material_ids")) for case in fixture["cases"]
    )
    return {
        "backend": name,
        "cases": len(results),
        "recall_at_5": round(sum(case["recall_at_5"] for case in results) / len(results), 4),
        "recall_at_10": round(sum(case["recall_at_10"] for case in results) / len(results), 4),
        "mrr": round(sum(case["mrr"] for case in results) / len(results), 4),
        "ndcg_at_10": round(sum(case["ndcg_at_10"] for case in results) / len(results), 4),
        "material_hit_rate_at_5": round(material_hits / max(expected_material_case_count, 1), 4),
        "mean_latency_ms": round(sum(latency_ms) / len(latency_ms), 3),
        "p95_latency_ms": round(_percentile(latency_ms, 0.95), 3),
        "forbidden_hits": forbidden_hits,
        "empty_query_compatible": compatibility_passed,
        "per_case": results,
    }


async def run_evaluation(backend_name: str, *, include_qdrant: bool = False) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="mnemox-retrieval-eval-") as temporary:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(temporary) / 'evaluation.sqlite3'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as db:
                rag = _ephemeral_rag()
                owners = await _seed(db, fixture, rag)
                keyword = KeywordMaterialRetrievalBackend(db)
                chroma = ChromaMaterialRetrievalBackend(db, rag=rag)
                hybrid = HybridMaterialRetrievalBackend(chroma, keyword)
                candidates: dict[str, Any] = {
                    "keyword": keyword,
                    "chroma": chroma,
                    "hybrid": hybrid,
                }

                no_embedding = _ephemeral_rag()
                no_embedding._collection = rag._collection
                no_embedding._embed_model = None
                candidates["hybrid_no_embedding"] = HybridMaterialRetrievalBackend(
                    ChromaMaterialRetrievalBackend(db, rag=no_embedding), keyword
                )

                qdrant = None
                if include_qdrant or backend_name.startswith("qdrant"):
                    from app.services.qdrant_retrieval_spike import QdrantMaterialRetrievalSpike

                    qdrant = QdrantMaterialRetrievalSpike(
                        db,
                        embedding_model=DeterministicEmbedding(),
                        dimension=DIMENSION,
                    )
                    materials = list((await db.scalars(select(Material))).all())
                    for material in materials:
                        await qdrant.index_material(material, user_id=int(material.user_id))
                    rerank = QdrantMaterialRetrievalSpike(
                        db,
                        embedding_model=DeterministicEmbedding(),
                        dimension=DIMENSION,
                        rerank=True,
                        client=qdrant.client,
                        collection_name=qdrant.collection_name,
                    )
                    sparse_only = QdrantMaterialRetrievalSpike(
                        db,
                        embedding_model=None,
                        dimension=DIMENSION,
                        client=qdrant.client,
                        collection_name=qdrant.collection_name,
                    )
                    candidates.update(
                        {
                            "qdrant": qdrant,
                            "qdrant_rerank": rerank,
                            "qdrant_no_embedding": sparse_only,
                        }
                    )

                if backend_name != "all" and backend_name not in candidates:
                    raise ValueError(f"Unsupported backend: {backend_name}")
                names = list(candidates) if backend_name == "all" else [backend_name]
                evaluations = [
                    await _evaluate_backend(name, candidates[name], db, fixture, owners)
                    for name in names
                ]

                # Prove that canonical source removal, sparse cleanup, and optional
                # Qdrant cleanup do not leave retrievable or cross-user artifacts.
                target = await db.get(Material, 112)
                projection_service = RetrievalProjectionService(db, rag=rag)
                await projection_service.prepare_forget(1, 112)
                await db.delete(target)
                await db.commit()
                deleted_projection = await projection_service.forget(1, 112)
                if qdrant is not None:
                    await qdrant.remove_material(112, user_id=1)
                deleted_router = RetrievalRouter(db, material_backend=hybrid)
                residual = await deleted_router.search(
                    "Recall MRR NDCG P95", user_id=1, source_types=("material",), top_k=10
                )
                stale = [hit for hit in residual if int(hit.source_id) == 112]

                return {
                    "fixture": str(FIXTURE.relative_to(Path(__file__).resolve().parent)),
                    "fixture_version": fixture["version"],
                    "documents": len(fixture["materials"]),
                    "queries": len(fixture["cases"]),
                    "embedding": "deterministic local 64-dimensional token hash; no external API",
                    "results": evaluations,
                    "lifecycle_probes": {
                        "deleted_projection_status": deleted_projection["status"],
                        "deleted_material_residual_hits": len(stale),
                        "user_isolation_violations": sum(item["forbidden_hits"] for item in evaluations),
                        "empty_query_compatible": all(item["empty_query_compatible"] for item in evaluations),
                    },
                }
        finally:
            await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("keyword", "chroma", "hybrid", "hybrid_no_embedding", "qdrant", "qdrant_rerank", "qdrant_no_embedding", "all"),
        default="hybrid",
    )
    parser.add_argument("--include-qdrant", action="store_true")
    parser.add_argument("--min-recall-at-5", type=float, default=0.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(run_evaluation(args.backend, include_qdrant=args.include_qdrant))
    if args.summary_only:
        for result in report["results"]:
            result.pop("per_case", None)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(output + "\n", encoding="utf-8")
    print(output)
    if any(item["recall_at_5"] < args.min_recall_at_5 for item in report["results"]):
        return 2
    if report["lifecycle_probes"]["deleted_material_residual_hits"]:
        return 3
    if report["lifecycle_probes"]["user_isolation_violations"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
