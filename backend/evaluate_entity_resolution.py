"""Offline Stage 3 resolution gate over the frozen Stage 0 corpus.

The semantic rankings are recorded synthetic fixtures, not live model output.
This keeps CI deterministic and verifies Top-K scoring, negative cases, and
tenant filtering. A configured provider still requires a release-time sample.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
ASSOCIATION_CASES = FIXTURES / "association_v2_eval_cases.json"
RECORDED_RANKINGS = FIXTURES / "knowledge_resolution_rankings.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_resolution_evaluation() -> dict[str, Any]:
    corpus = _load(ASSOCIATION_CASES)
    recorded = _load(RECORDED_RANKINGS)
    concepts = {int(row["id"]): row for row in corpus["concepts"]}
    implicit = {row["id"]: row for row in corpus["cases"] if row["scenario"] == "implicit"}
    rankings = {row["case_id"]: row["ranked_concept_ids"] for row in recorded["rankings"]}
    if set(rankings) != set(implicit):
        missing = sorted(set(implicit) - set(rankings))
        extra = sorted(set(rankings) - set(implicit))
        raise ValueError(f"resolution ranking fixture drift: missing={missing}, extra={extra}")

    positive_count = 0
    top1_hits = 0
    top5_hits = 0
    negative_count = 0
    correct_negative_count = 0
    cross_user_hits = 0
    result_rows: list[dict[str, Any]] = []
    for case_id in sorted(implicit):
        case = implicit[case_id]
        user_id = int(case["user_id"])
        raw_ids = [int(value) for value in rankings[case_id]]
        visible_ids = []
        for concept_id in raw_ids:
            concept = concepts.get(concept_id)
            if concept is None or int(concept["user_id"]) != user_id:
                cross_user_hits += 1
                continue
            if concept_id not in visible_ids:
                visible_ids.append(concept_id)
        expected = {int(value) for value in case["expected_concept_ids"]}
        if expected:
            positive_count += 1
            top1_hits += int(bool(visible_ids[:1] and expected.intersection(visible_ids[:1])))
            top5_hits += int(bool(expected.intersection(visible_ids[:5])))
        else:
            negative_count += 1
            correct_negative_count += int(not visible_ids)
        result_rows.append(
            {
                "case_id": case_id,
                "visible_top5": visible_ids[:5],
                "expected": sorted(expected),
            }
        )

    top1 = top1_hits / positive_count if positive_count else 1.0
    top5 = top5_hits / positive_count if positive_count else 1.0
    negative_accuracy = correct_negative_count / negative_count if negative_count else 1.0
    threshold = float(recorded["semantic_top5_recall_threshold"])
    digest = hashlib.sha256(
        json.dumps(result_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fixture_version": recorded["version"],
        "evaluation_kind": "recorded_synthetic_embedding_rankings",
        "external_model_calls": 0,
        "positive_cases": positive_count,
        "negative_cases": negative_count,
        "semantic_top1_recall": round(top1, 6),
        "semantic_top5_recall": round(top5, 6),
        "semantic_top5_threshold": threshold,
        "semantic_top5_gate_passed": top5 >= threshold,
        "negative_accuracy": round(negative_accuracy, 6),
        "cross_user_hits": cross_user_hits,
        "automatic_semantic_merges": 0,
        "deterministic_result_sha256": digest,
    }


if __name__ == "__main__":
    print(json.dumps(run_resolution_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))

