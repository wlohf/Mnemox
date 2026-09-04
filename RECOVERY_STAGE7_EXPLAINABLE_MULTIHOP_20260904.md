# Mnemox Stage 7 Explainable Multi-hop Recovery Checkpoint

> Created: 2026-09-04
> Branch: `backup/stage7-explainable-multihop-20260904`
> Parent checkpoint: `backup/stage7-knowledge-path-20260904`
> Status: recovery-only / non-merge-ready

## Scope

This checkpoint preserves Stage 7 Phase 3.2 Explainable Multi-hop Association V1.

Key behavior:

- default-off `ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED`;
- explanation runs after ranking and does not alter candidate score/order;
- shared-Concept explanations do not require Neo4j traversal;
- multi-hop explanations use bounded Concept paths from GraphStore;
- every Concept / ConceptEdge / provenance item is rehydrated from user-scoped Canonical SQL;
- graph failure / stale projection / outside rollout / path mismatch only removes optional explanation;
- the underlying Association result remains available;
- no LLM-generated reason is used;
- the new `explanation` surface does not expose Claim/Concept/Edge SQL IDs, Neo4j keys, or Cypher.

## Verification

Focused explanation + Association tests:

```text
16 passed
```

Stage 0-7 Knowledge wide regression with real Neo4j integration included:

```text
127 passed, 1 warning
```

The warning is the pre-existing third-party Graphiti/Pydantic deprecation.

`git diff --check` passed for the Phase 3.2 task files.

## SHA256 inventory

```text
8fa4048da4a0b011c3dc7a67ad06ce717bf48269d396473cd8d48839fb219293  backend/app/services/association_explanation_service.py
e1b35102a4aff42fcc0bcbc16c01d0f890e27b1a9bfa7af91e644ce9875f0826  backend/app/services/association_v2_service.py
1b60d180beeaa2906ddff0856727ad27e4faa6b4b5bb7afb586ef2f0e77a6eb3  backend/tests/test_association_explanation.py
ae99c8f249fdfaa34606b6a25b37b865472b55e15269fae942f1558a77bdf60a  backend/tests/test_association_v2.py
99f76539386e0b2dcb97593d6519525fc0fe531b4825e2ab484cf68af57a50ac  docs/superpowers/specs/2026-09-04-mnemox-v2-explainable-multihop-association-contract.md
f4dd0ff8b1f49e985395ea36727895bad3e5fff5604302745aea9880972b6fc2  docs/updates/2026/2026-09-04_mnemox-v2-stage7-explainable-multihop.md
```

## Recovery warning

The active VPS checkout is historically dirty. This branch is a disaster-recovery checkpoint, not a merge-ready feature branch. Shared files must be reconstructed selectively onto a clean branch.

Phase 3 graph-native product capability is complete at V1 scope. The next block is real-data benchmark / long-running rollout observation, then Graphiti Temporal/Episodic Slice.
