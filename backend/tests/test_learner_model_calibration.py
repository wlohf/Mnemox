"""Offline learner-model replay benchmark and version comparison tests."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.learner_model_calibration_service import (
    CalibrationEvidence,
    HoldoutCase,
    ModelCalibrationConfig,
    _predict,
    build_holdout_cases,
    compare_model_versions,
)


NOW = datetime(2026, 8, 5, 12, 0, 0)


def _evidence(
    user_id: int,
    concept_id: int,
    day: int,
    score: float,
    *,
    evidence_id: int = 0,
) -> CalibrationEvidence:
    return CalibrationEvidence(
        evidence_id=evidence_id,
        user_id=user_id,
        concept_id=concept_id,
        evidence_type="review_result",
        score=score,
        reliability=0.9,
        observed_at=NOW + timedelta(days=day),
    )


def test_same_timestamp_evidence_uses_id_as_stable_tie_breaker():
    rows = [
        _evidence(1, 10, 0, 0.9, evidence_id=3),
        _evidence(1, 10, 0, 0.2, evidence_id=1),
        _evidence(1, 10, 0, 0.5, evidence_id=2),
    ]

    cases = build_holdout_cases(rows)

    assert len(cases) == 1
    assert [item.evidence_id for item in cases[0].history] == [1, 2]
    assert cases[0].target_score == 0.9


def test_reliability_multiplier_is_clamped_after_scaling():
    case = HoldoutCase(
        user_id=1,
        concept_id=10,
        history=(
            CalibrationEvidence(
                evidence_id=1,
                user_id=1,
                concept_id=10,
                evidence_type="review_result",
                score=1.0,
                reliability=0.9,
                observed_at=NOW,
            ),
            CalibrationEvidence(
                evidence_id=2,
                user_id=1,
                concept_id=10,
                evidence_type="answer",
                score=0.0,
                reliability=1.0,
                observed_at=NOW,
            ),
        ),
        target_score=0.5,
        target_at=NOW,
    )
    config = ModelCalibrationConfig(
        version="clamp-check",
        half_life_days=90.0,
        weights={"review_result": 1.0, "answer": 1.0},
        reliability_multipliers={"review_result": 2.0},
    )

    assert _predict(case, config) == 0.5


def test_holdout_cases_never_mix_users_or_concepts():
    rows = [
        _evidence(1, 10, 0, 0.3),
        _evidence(2, 10, 0, 0.9),
        _evidence(1, 10, 1, 0.5),
        _evidence(2, 10, 1, 0.8),
    ]

    cases = build_holdout_cases(rows)

    assert len(cases) == 2
    owner_case = next(case for case in cases if case.user_id == 1)
    other_case = next(case for case in cases if case.user_id == 2)
    assert [item.score for item in owner_case.history] == [0.3]
    assert [item.score for item in other_case.history] == [0.9]


def test_version_comparison_reports_metrics_but_blocks_small_sample_promotion():
    rows: list[CalibrationEvidence] = []
    for concept_id in range(5):
        rows.extend(
            [
                _evidence(1, concept_id + 1, 0, 0.4 + concept_id * 0.05),
                _evidence(1, concept_id + 1, 7, 0.5 + concept_id * 0.05),
            ]
        )

    report = compare_model_versions(rows, minimum_cases=50)

    assert report["dataset"]["holdout_cases"] == 5
    assert {item["version"] for item in report["versions"]} == {
        "explainable-rules-v1",
        "candidate-balanced-v2",
        "candidate-long-retention-v2",
    }
    assert all(item["mae"] is not None for item in report["versions"])
    assert report["recommendation"]["action"] == "collect_more_data"
    assert report["recommendation"]["minimum_cases"] == 50


def test_empty_dataset_produces_explicit_non_promotable_report():
    report = compare_model_versions([], minimum_cases=20)

    assert report["dataset"] == {
        "evidence_rows": 0,
        "user_concept_groups": 0,
        "holdout_cases": 0,
    }
    assert all(item["mae"] is None for item in report["versions"])
    assert report["recommendation"]["action"] == "collect_more_data"
