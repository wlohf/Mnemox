"""Mnemox V2 Stage 0 corpus, baseline, and disabled-feature contracts."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.config import Settings
from evaluate_knowledge import _rank_metrics, run_evaluation


FIXTURES = Path(__file__).parent / "fixtures"
EXTRACTION_FIXTURE = FIXTURES / "knowledge_extraction_eval_cases.json"
ASSOCIATION_FIXTURE = FIXTURES / "association_v2_eval_cases.json"
FEATURE_FLAGS = (
    "KNOWLEDGE_V2_ENABLED",
    "KNOWLEDGE_LLM_EXTRACTION_ENABLED",
    "KNOWLEDGE_EMBEDDING_ENABLED",
    "ASSOCIATION_V2_ENABLED",
    "ASSOCIATION_V2_SHADOW",
    "KNOWLEDGE_SEMANTIC_AUTO_RESOLVE_ENABLED",
    "NEO4J_GRAPH_ENABLED",
    "NEO4J_GRAPH_SHADOW",
    "GRAPHITI_ENABLED",
    "GRAPHITI_SHADOW",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_extraction_fixture_has_fifty_grounded_human_annotations_without_real_user_data():
    fixture = _load(EXTRACTION_FIXTURE)
    units = fixture["units"]
    annotated = [unit for unit in units if unit["claims"]]

    assert fixture["annotation_provenance"] == "synthetic-human-authored-and-reviewed"
    assert fixture["privacy"]["contains_real_user_data"] is False
    assert len(annotated) >= 50
    assert {unit["language"] for unit in units} == {"zh", "en"}
    assert {unit["concept_mode"] for unit in units} >= {"explicit", "implicit", "none"}
    assert {unit["source"]["type"] for unit in units} >= {"material", "note"}
    assert any(unit["source"]["status"] == "deleted" for unit in units)
    assert {unit["user_id"] for unit in units} >= {1, 2}
    assert any(not unit["claims"] for unit in units)

    local_ids = set()
    for unit in annotated:
        assert unit["id"] not in local_ids
        local_ids.add(unit["id"])
        for claim in unit["claims"]:
            assert claim["statement"].strip()
            assert claim["claim_kind"] in {
                "definition",
                "principle",
                "causal",
                "recommendation",
                "comparison",
                "observation",
            }
            assert claim["evidence"]
            assert all(evidence["quote"] in unit["content"] for evidence in claim["evidence"])
            assert claim["concepts"]

    serialized = json.dumps(fixture, ensure_ascii=False).lower()
    assert "mne_mox_synthetic_tenant_" in serialized
    assert "sk-" not in serialized
    assert "api_key=" not in serialized
    assert "bearer " not in serialized


def test_association_fixture_has_cross_source_quality_and_lifecycle_coverage():
    fixture = _load(ASSOCIATION_FIXTURE)
    cases = fixture["cases"]
    sources = {source["key"]: source for source in fixture["evidence_sources"]}
    tags = Counter(tag for case in cases for tag in case["tags"])

    assert fixture["privacy"]["contains_real_user_data"] is False
    assert len(cases) >= 50
    assert {case["scenario"] for case in cases} == {"explicit", "implicit"}
    assert {case["language"] for case in cases} == {"zh", "en"}
    assert tags["synonym"] > 0
    assert tags["implicit_concept"] > 0
    assert tags["negative"] > 0
    assert tags["cross_user_sentinel"] > 0
    assert tags["deletion"] > 0
    assert len({case["anchor_source_key"] for case in cases}) == len(cases)
    assert all(case["query"].strip() for case in cases)
    assert all("forbidden_user_ids" in case for case in cases)

    for case in cases:
        assert case["anchor_source_key"].split(":", 1)[0] == "material"
        for source_key in case["expected_related_source_keys"]:
            assert source_key in sources
            assert sources[source_key]["source_type"] != "material"
            assert int(sources[source_key]["user_id"]) == int(case["user_id"])


def test_knowledge_v2_flags_are_declared_off_and_limits_are_bounded():
    fields = Settings.model_fields
    assert all(fields[name].default is False for name in FEATURE_FLAGS)
    assert fields["KNOWLEDGE_EXTRACTION_MAX_UNIT_CHARS"].default == 8_000
    assert fields["KNOWLEDGE_EXTRACTION_MAX_CLAIMS_PER_UNIT"].default == 12
    assert fields["KNOWLEDGE_CLAIM_MAX_CHARS"].default == 500
    assert fields["KNOWLEDGE_EXTRACTION_MAX_OUTPUT_CHARS"].default == 12_000
    assert fields["KNOWLEDGE_EXTRACTION_TIMEOUT_SECONDS"].default == 30.0
    assert fields["KNOWLEDGE_LLM_MAX_CALLS_PER_RUN"].default == 64
    assert fields["KNOWLEDGE_LLM_MAX_ESTIMATED_TOKENS_PER_RUN"].default == 64_000
    assert fields["KNOWLEDGE_LLM_DAILY_ESTIMATED_TOKENS_PER_USER"].default == 256_000
    assert fields["KNOWLEDGE_EXTRACTION_WORKER_POLL_INTERVAL_SECONDS"].default == 2.0
    assert fields["KNOWLEDGE_EXTRACTION_WORKER_BATCH_SIZE"].default == 4
    assert fields["KNOWLEDGE_EXTRACTION_MAX_ATTEMPTS"].default == 5
    assert fields["KNOWLEDGE_EXTRACTION_LEASE_SECONDS"].default == 120
    assert fields["KNOWLEDGE_EXTRACTION_RETRY_BASE_SECONDS"].default == 5.0
    assert fields["KNOWLEDGE_CHROMA_COLLECTION_NAME"].default == "mnemox_knowledge"
    assert fields["KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS"].default == 20.0
    assert fields["KNOWLEDGE_RESOLUTION_TOP_K"].default == 5
    assert fields["KNOWLEDGE_RESOLUTION_LEXICAL_THRESHOLD"].default == 0.45
    assert fields["KNOWLEDGE_RESOLUTION_MAX_MENTIONS_PER_CLAIM"].default == 8
    assert fields["KNOWLEDGE_PROJECTION_WORKER_POLL_INTERVAL_SECONDS"].default == 2.0
    assert fields["KNOWLEDGE_PROJECTION_WORKER_BATCH_SIZE"].default == 20
    assert fields["KNOWLEDGE_PROJECTION_MAX_ATTEMPTS"].default == 5
    assert fields["KNOWLEDGE_PROJECTION_LEASE_SECONDS"].default == 120
    assert fields["KNOWLEDGE_PROJECTION_RETRY_BASE_SECONDS"].default == 5.0


def test_rank_metrics_handle_positive_negative_and_duplicate_results():
    assert _rank_metrics([9, 1, 1], [1, 2]) == {"recall_at_5": 0.5, "mrr": 0.5}
    assert _rank_metrics([], []) == {"recall_at_5": 1.0, "mrr": 1.0}
    assert _rank_metrics([1], []) == {"recall_at_5": 0.0, "mrr": 0.0}


@pytest.mark.asyncio
async def test_association_v1_baseline_is_repeatable_local_and_lifecycle_safe(monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Stage 0 baseline must not open a network connection")

    monkeypatch.setattr("socket.socket.connect", deny_network)
    first = await run_evaluation()
    second = await run_evaluation()

    assert first["questions"] >= 50
    assert first["external_model_calls"] == 0
    assert first["deterministic_result_sha256"] == second["deterministic_result_sha256"]
    assert first["results"]["explicit"]["recall_at_5"] >= 0.95
    assert first["results"]["explicit"]["mrr"] >= 0.95
    # This is the intended Stage 0 gap: V1 cannot recover implicit concepts.
    assert first["results"]["implicit"]["recall_at_5"] == 0.0
    assert first["results"]["implicit"]["no_result_rate"] >= 0.85
    assert first["lifecycle_probes"] == {
        "user_isolation_violations": 0,
        "deleted_source_residual_hits": 0,
    }
