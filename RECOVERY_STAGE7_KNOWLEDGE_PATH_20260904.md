# Mnemox Stage 7 Knowledge Path Recovery Checkpoint

> Created: 2026-09-04
> Branch: `backup/stage7-knowledge-path-20260904`
> Parent checkpoint: `backup/stage7-readiness-20260904`
> Status: recovery-only / non-merge-ready

## Scope

This checkpoint preserves Stage 7 Phase 3.1: the first graph-native Knowledge / Learning Path capability.

Key behavior:

- `POST /api/knowledge/learning-path` behind `KNOWLEDGE_PATH_ENABLED`.
- Neo4j performs bounded Concept path traversal only.
- SQL remains Canonical for Concept identity, ConceptEdge truth, learner mastery/evidence, provenance, review and lifecycle state.
- Default path semantics follow `prerequisite_of` outgoing direction; `related_to` is explicit opt-in and symmetric.
- Graph results are rehydrated and revalidated from SQL before returning product output.
- stale projection / outside rollout / Neo4j unavailable => this advanced capability is unavailable; no generic SQL BFS is invented.
- basic product reads continue to use SQL/fallback normally.
- every hop exposes structured provenance: confirmed evidence, confirmed manual, or explicit missing evidence.

## Verification

Targeted path/runtime suite:

```text
31 passed, 2 skipped
```

The two skips were due only to absent `MNEMOX_TEST_NEO4J_*` variables in that process.

Real disposable Neo4j 5.26 Knowledge Path integration was then run explicitly:

```text
2 passed
```

Stage 0-7 Knowledge wide regression with the real Neo4j path integration included:

```text
122 passed, 1 warning
```

No tests were skipped in that wide run. The only warning is the existing third-party Graphiti/Pydantic deprecation.

`git diff --check` passed for the Stage 7 Knowledge Path task files.

## SHA256 inventory

```text
b493b20916a534b07d80dee00af85ca7b8b73e3fc1f4ce3d393754d08b2d8c75  backend/app/services/knowledge_path_service.py
91d085c3fe9fbc06aba578567b30a7fd603a6d36a5ea3a37d6e39b9839d7204f  backend/app/services/graph_store/neo4j_store.py
03f3069c6939bae3fd2c589d9aa97cfdf8c90376e113919208b500aee4bebc69  backend/app/routers/knowledge.py
4d1f401ac923a391b602c03cc495b3a4e753293b8971a663e5dc2a948e089f6c  backend/tests/test_knowledge_path.py
3db77da2cab8210e01c220a585ad9467fa5dfdd0762bb7615bf74342bcf0c28d  backend/tests/test_knowledge_path_api.py
2afb31b205845a08681f5455d82422665090ec7f1f9a571278c931c97e05a3d1  backend/tests/test_neo4j_knowledge_path_integration.py
2067f2f2b78f61698f67dfcc3507c5902eeee3f2364e4cc6e6b81849defdb2ac  docs/superpowers/specs/2026-09-04-mnemox-v2-knowledge-learning-path-contract.md
540d5c85aa918dc08dc622a1b4f1f9cdb777f80e0a50c20eaba4b45f01a103e6  docs/updates/2026/2026-09-04_mnemox-v2-stage7-knowledge-path.md
```

## Recovery warning

The active VPS checkout is historically dirty. This branch is a disaster-recovery checkpoint, not a claim that the whole checkout is merge-ready. Shared files must be selectively reconstructed onto a clean branch rather than merged wholesale.

The next independent block after this checkpoint is Phase 3.2 Explainable Multi-hop Association.
