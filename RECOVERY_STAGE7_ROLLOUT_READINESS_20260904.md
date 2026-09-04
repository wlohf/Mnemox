# Mnemox Stage 7 Rollout / Readiness Recovery Checkpoint

> Created: 2026-09-04
> Branch: `backup/stage7-rollout-readiness-20260904`
> Parent recovery branch: `backup/stage7-readiness-20260904`
> Parent recovery commit: `42ec1364965ed8caf6138a5c3c01f92fb6ffeeb3`
> Local committed HEAD: `97036f490422f06fff3a5bec22232ef1ebe91c4b`
> Status: **recovery-only / non-merge-ready**

## Purpose

This checkpoint preserves the Stage 7 Optional Neo4j Runtime block after rollout gating, stale-projection protection, projection lifecycle closure, and real SQL/Neo4j parity verification.

The active VPS checkout is historically dirty. It was **not** staged, reset, stashed, cleaned, or bulk-committed while creating this checkpoint. This branch is a disaster-recovery asset, not a clean feature branch and must not be merged wholesale into `main`.

## Architecture preserved

- PostgreSQL / SQLite remain Canonical Knowledge / Source of Truth.
- Neo4j remains an optional, disposable, SQL-rebuildable Graph Execution Projection.
- `GRAPH_BACKEND=sql` remains the default.
- Stage 6 default Runtime NO-GO evidence remains valid; Stage 7 does not rewrite that decision.
- GraphStore remains storage-neutral; SQL is not expanded into a generic graph algorithm engine for parity.
- Graphiti remains a separate future Temporal/Episodic slice and does not replace `MemoryDeclaration`.

## Scope completed in this checkpoint

1. Stable rollout policy:
   - `NEO4J_GRAPH_ROLLOUT_PERCENT=0..100`
   - `NEO4J_GRAPH_ROLLOUT_USER_IDS` explicit canary allowlist
   - stable SHA-256 per-user bucket instead of process-random Python hashing.
2. Runtime stale-graph gate:
   - outside rollout -> SQL directly;
   - projection status unavailable -> SQL directly;
   - uninitialized / pending / processing / failed / DLQ -> SQL directly;
   - rollout selected + initialized + caught-up -> Neo4j is attempted;
   - Neo4j query failure -> existing request-scoped SQL fallback.
3. Initialization semantics:
   - an empty canonical graph is initialized by definition;
   - a user with existing canonical Source/Concept graph data requires evidence of a successful Neo4j `rebuild_user` before Neo4j reads are allowed.
4. Projection lifecycle closure:
   - graph-affecting Claim / Concept / relation mutations requeue Neo4j rebuild;
   - rebuild remains full-user and rebuildable rather than prematurely adding per-edge incremental complexity;
   - a processed rebuild cannot silently remain `ready` after new canonical mutations.
5. In-flight dirty coalescing:
   - fixed primary rebuild slot + fixed follow-up slot;
   - repeated mutations during an in-flight rebuild reuse the follow-up instead of creating rebuild storms;
   - same-user Neo4j tasks cannot be claimed concurrently;
   - actual rebuild execution reuses `serialized_user_operation(namespace="neo4j-graph-rebuild")`, giving local asyncio serialization and PostgreSQL advisory-lock serialization across workers.
6. Status responsibility cleanup:
   - Neo4j lag/initialization diagnostics moved to neutral `graph_projection_status_service.py`, avoiding a `graph_shadow_service <-> graph_store` import cycle.
7. Real backend parity and stale-gate acceptance:
   - disposable `neo4j:5.26-community` used locally;
   - repeated rebuild is idempotent;
   - SQL vs Neo4j fixed-path results match on ID / path type / depth / confidence;
   - `source_claims` parity passes;
   - wrong credentials do not poison Canonical SQL transactions;
   - cross-user isolation, source delete, and no-raw-property boundaries pass;
   - after a successful rebuild, runtime reads actually use Neo4j;
   - after a new Canonical Concept mutation, the same runtime store immediately routes back to SQL until rebuild catches up.

## Verification evidence

Final Stage 0-7 Knowledge regression was run with a real disposable Neo4j service, not skipped:

```text
104 passed, 0 skipped, 1 warning
```

Covered suites:

```text
test_knowledge_stage0.py
test_knowledge_source_lifecycle.py
test_knowledge_extraction.py
test_entity_resolution.py
test_knowledge_projection.py
test_sparse_knowledge_index.py
test_association_v2.py
test_graph_store_contract.py
test_graph_store_rollout.py
test_graph_runtime_status.py
test_neo4j_projection_lifecycle.py
test_graph_shadow_stage6.py
test_neo4j_shadow_integration.py
```

The one warning is the existing third-party `graphiti_core` Pydantic v2 class-based config deprecation warning.

The disposable Neo4j container and `mnemox_neo4j_shadow_data` volume were removed after verification.

`git diff --check` passed for the task-related files before this checkpoint.

## SHA256 inventory

```text
f8932e9bbb4291e19b2119f79841b83dba1e0a11a1040494e6dfc42bdd297793  backend/app/services/graph_store/rollout_store.py
feee4b383c049663fc21d4608e4a3a0a6d5905176c84d2083510abfad0fd63fa  backend/app/services/graph_projection_status_service.py
3d45a1f84ed6e7daf4915eb6bb0cffd939ad1bf04b09eee4bbd5b003b2a4e971  backend/app/services/graph_runtime_status_service.py
65669c34ab55181a126c9431aeede3bcae1d63aa83979eaf624b209c0be2cb56  backend/app/services/knowledge_projection_service.py
861f78b978a6dc979e58cb45557eabae4c646a9b4e1d5b7566fa282d1a076c18  backend/app/services/claim_relation_service.py
2d54c18ccc5b0479c0f3d98fd58876c96e4d10e909437e6f68da63a7886d4e9a  backend/app/services/concept_service.py
61bc7018f7af12bb8bca32d5b32b1e7fd403d3126c4dcb7628a74622bd46df95  backend/app/services/concept_graph_service.py
d71c1d082cfbf142360103ec340fb121e57e4d8237b689e36bef2b454055e2dd  backend/app/services/graph_shadow_service.py
8169f91a64026460bce4093ee3d91ad258b0b645c0e855aea184aa1358bd0411  backend/tests/test_graph_store_rollout.py
277824452796fe0356eb6a600bc216f18f449b471349ec93ca0fbb0ddf4bf42f  backend/tests/test_graph_runtime_status.py
772d1bc9b6ec19bc994d5291e2385437aa4ddf811f2b1b8a08689417e6fdd8d7  backend/tests/test_neo4j_projection_lifecycle.py
a3e498e6feafbd904014c5c6f131982e4528471a9c51a7c4c5fdaccd95932ec8  backend/tests/test_neo4j_shadow_integration.py
9c1e6d3169c40ff44755e6efb39268972d47c1519270399c960f4e3c8ce49499  backend/app/services/graph_store/factory.py
e9ee5ee75e82c3e31dfff5ff382b62dc7a102fab7b3575e6e4311ceebbc38a73  backend/app/config.py
1ed556909fe5354e87080182614e5f5b18a9f71815f7ba16790f88d0614b2d06  .env.example
e76570023c2574c3b4f361a5470192992234a5b6e6b5c3206a35306f249a09fe  backend/env.example
fa7e7fb7e5222b4000442d206b1c862a2066c6f1952e1044875322ce478d8c10  docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md
df39565c8056af26ccf574c7502dc4f695aebff6a179a09fb1840ac6aec5d8e6  docs/updates/2026/2026-09-04_mnemox-v2-stage7-neo4j-rollout-readiness.md
3bfce82bf026410265ce7074eb660135a02ba10a9973b6d7cee158bde49e8740  docs/updates/2026/2026-09-04_mnemox-v2-stage7-graph-domain-contract.md
151e018a676bd6e968a75d25e96c6a74a21edd6e6b5d412d8763857cab6ba7e5  docs/roadmap.md
bac9d23bdac8907646a3c42fe101e60f9791df0eaaa6d22514210160a2ef9aae  docs/progress.md
61fde68f75e1f2434c5cd2aff69154aaeeb615c6876ce1e469323a8eb2fd4eb9  docs/technical.md
```

## Recovery rule

Files saved on this branch or under its recovery snapshot should be treated as the authoritative source for this milestone. Shared files such as `config.py`, projection services, concept services, and top-level docs may contain unrelated historical dirty-checkout work; their exact hashes are recorded so they can be compared or selectively restored without pretending they are clean merge patches.

The next Stage 7 construction point is Phase 3: implement the first graph-native product capability, Knowledge / Learning Path. Do not restore a future Phase 3 implementation when the desired rollback target is this checkpoint.
