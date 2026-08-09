"""Privacy-minimized offline replay benchmark for learner-model versions."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learner_model import LearnerEvidence


@dataclass(frozen=True)
class CalibrationEvidence:
    evidence_id: int
    user_id: int
    concept_id: int
    evidence_type: str
    score: float
    reliability: float
    observed_at: datetime


@dataclass(frozen=True)
class HoldoutCase:
    user_id: int
    concept_id: int
    history: tuple[CalibrationEvidence, ...]
    target_score: float
    target_at: datetime


@dataclass(frozen=True)
class ModelCalibrationConfig:
    version: str
    half_life_days: float
    weights: Mapping[str, float]
    reliability_multipliers: Mapping[str, float]


BASE_WEIGHTS = {
    "answer": 1.0,
    "recall": 1.1,
    "explanation": 1.15,
    "application": 1.25,
    "hint_count": 0.75,
    "review_result": 1.0,
    "legacy_mastery": 0.35,
}

MODEL_CANDIDATES = (
    ModelCalibrationConfig(
        version="explainable-rules-v1",
        half_life_days=90.0,
        weights=BASE_WEIGHTS,
        reliability_multipliers={},
    ),
    ModelCalibrationConfig(
        version="candidate-balanced-v2",
        half_life_days=75.0,
        weights={
            **BASE_WEIGHTS,
            "recall": 1.2,
            "explanation": 1.25,
            "application": 1.35,
            "review_result": 1.1,
        },
        reliability_multipliers={"review_result": 1.05, "legacy_mastery": 0.8},
    ),
    ModelCalibrationConfig(
        version="candidate-long-retention-v2",
        half_life_days=120.0,
        weights={**BASE_WEIGHTS, "review_result": 1.1},
        reliability_multipliers={"review_result": 1.05, "legacy_mastery": 0.8},
    ),
)

TARGET_TYPES = frozenset(set(BASE_WEIGHTS) - {"legacy_mastery"})


def _normalized_quality(item: CalibrationEvidence) -> float:
    score = max(0.0, min(1.0, float(item.score)))
    return 1.0 - score if item.evidence_type == "hint_count" else score


def build_holdout_cases(rows: Iterable[CalibrationEvidence]) -> list[HoldoutCase]:
    """Use the latest real direct outcome as a holdout for each user/concept."""
    grouped: dict[tuple[int, int], list[CalibrationEvidence]] = defaultdict(list)
    for row in rows:
        if row.evidence_type in BASE_WEIGHTS:
            grouped[(int(row.user_id), int(row.concept_id))].append(row)

    cases: list[HoldoutCase] = []
    for (user_id, concept_id), group in grouped.items():
        ordered = sorted(group, key=lambda item: (item.observed_at, item.evidence_id))
        target_index = next(
            (index for index in range(len(ordered) - 1, 0, -1) if ordered[index].evidence_type in TARGET_TYPES),
            None,
        )
        if target_index is None:
            continue
        target = ordered[target_index]
        history = tuple(ordered[:target_index])
        if not history:
            continue
        cases.append(
            HoldoutCase(
                user_id=user_id,
                concept_id=concept_id,
                history=history,
                target_score=_normalized_quality(target),
                target_at=target.observed_at,
            )
        )
    return cases


def _predict(case: HoldoutCase, config: ModelCalibrationConfig) -> float | None:
    weighted_score = 0.0
    total_weight = 0.0
    for item in case.history:
        base_weight = config.weights.get(item.evidence_type)
        if base_weight is None:
            continue
        age_days = max(0.0, (case.target_at - item.observed_at).total_seconds() / 86400.0)
        recency_weight = 0.5 ** (age_days / config.half_life_days)
        reliability = max(0.0, min(1.0, float(item.reliability)))
        reliability = max(
            0.0,
            min(
                1.0,
                reliability * config.reliability_multipliers.get(item.evidence_type, 1.0),
            ),
        )
        weight = float(base_weight) * reliability * recency_weight
        weighted_score += _normalized_quality(item) * weight
        total_weight += weight
    return weighted_score / total_weight if total_weight > 0 else None


def _evaluate(cases: list[HoldoutCase], config: ModelCalibrationConfig) -> dict[str, Any]:
    pairs = [
        (prediction, case.target_score)
        for case in cases
        if (prediction := _predict(case, config)) is not None
    ]
    if not pairs:
        return {
            "version": config.version,
            "half_life_days": config.half_life_days,
            "cases": 0,
            "mae": None,
            "rmse": None,
            "binary_brier": None,
        }
    absolute_errors = [abs(prediction - target) for prediction, target in pairs]
    squared_errors = [(prediction - target) ** 2 for prediction, target in pairs]
    binary_brier = [
        (prediction - (1.0 if target >= 0.7 else 0.0)) ** 2
        for prediction, target in pairs
    ]
    return {
        "version": config.version,
        "half_life_days": config.half_life_days,
        "cases": len(pairs),
        "mae": round(sum(absolute_errors) / len(pairs), 6),
        "rmse": round(math.sqrt(sum(squared_errors) / len(pairs)), 6),
        "binary_brier": round(sum(binary_brier) / len(pairs), 6),
    }


def compare_model_versions(
    rows: Iterable[CalibrationEvidence],
    *,
    minimum_cases: int = 50,
    minimum_mae_improvement: float = 0.02,
) -> dict[str, Any]:
    evidence = list(rows)
    groups = {(int(item.user_id), int(item.concept_id)) for item in evidence}
    cases = build_holdout_cases(evidence)
    versions = [_evaluate(cases, config) for config in MODEL_CANDIDATES]
    baseline = versions[0]

    if len(cases) < int(minimum_cases):
        recommendation = {
            "action": "collect_more_data",
            "reason": "holdout_cases_below_promotion_threshold",
            "minimum_cases": int(minimum_cases),
            "current_cases": len(cases),
        }
    else:
        eligible = [item for item in versions if item["mae"] is not None]
        best = min(eligible, key=lambda item: float(item["mae"]))
        improvement = float(baseline["mae"]) - float(best["mae"])
        if best["version"] != baseline["version"] and improvement >= minimum_mae_improvement:
            recommendation = {
                "action": "review_candidate",
                "version": best["version"],
                "mae_improvement": round(improvement, 6),
                "requires_compatibility_review": True,
            }
        else:
            recommendation = {
                "action": "keep_baseline",
                "version": baseline["version"],
                "best_observed_version": best["version"],
                "mae_improvement": round(max(0.0, improvement), 6),
            }

    return {
        "benchmark": "leave_latest_direct_evidence_out",
        "dataset": {
            "evidence_rows": len(evidence),
            "user_concept_groups": len(groups),
            "holdout_cases": len(cases),
        },
        "versions": versions,
        "recommendation": recommendation,
        "privacy": "aggregate_metrics_only",
    }


async def build_database_calibration_report(
    db: AsyncSession,
    *,
    minimum_cases: int = 50,
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(LearnerEvidence).where(
                LearnerEvidence.evidence_category.in_(("direct", "legacy"))
            )
        )
    ).scalars().all()
    evidence = [
        CalibrationEvidence(
            evidence_id=int(row.id),
            user_id=int(row.user_id),
            concept_id=int(row.concept_id),
            evidence_type=str(row.evidence_type),
            score=float(row.score),
            reliability=float(row.reliability),
            observed_at=row.observed_at,
        )
        for row in rows
    ]
    return compare_model_versions(evidence, minimum_cases=minimum_cases)
