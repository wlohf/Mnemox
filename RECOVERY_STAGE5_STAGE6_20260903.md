# Mnemox Stage 5 / Stage 6 Recovery Manifest

> Created: 2026-09-04
> Branch: `backup/stage5-stage6-recovery-20260903`
> Base commit: `ac12ea5698d8b5a5370579a0e432a5ea1d37fa6e`
> Status: **recovery asset / non-merge-ready**

## Why this branch is intentionally not merge-ready

The active VPS checkout contains the complete Knowledge V2 Stage 0-6 development state, but it also contains a large amount of unrelated historical dirty/untracked work. The existing `ac12ea5` recovery commit is a Stage 4 core disaster-recovery point, not a complete Stage 0-4 application closure.

Therefore this branch deliberately does **not** pretend that copying all local dirty files into GitHub would create a clean feature branch. It preserves the verified recovery baseline and records the exact Stage 5/6 source identities, test evidence and reconstruction requirements.

Do not merge this branch into `main` as-is.

## Authoritative local recovery source

Workspace checkout used for the verified Stage 5/6 implementation:

```text
/home/cloudcli/projects/mnemox
local committed base HEAD: 97036f490422f06fff3a5bec22232ef1ebe91c4b
Stage 4 recovery base:     ac12ea5698d8b5a5370579a0e432a5ea1d37fa6e
```

The Stage 5/6 files below were present and verified in that checkout when this manifest was created.

## Stage 5 engineering status

Stage 5 engineering is complete. Product-quality acceptance on a real anonymous Chinese/bilingual corpus and human association quality is intentionally deferred.

Verified architecture:

- `SparseKnowledgeIndex` abstraction.
- default `auto` backend: SQLite FTS5 / PostgreSQL native GIN FTS.
- reference fallback on user-facing sparse search failure.
- claim-level dirty markers with incremental repair and full rebuild threshold.
- dirty writes isolated inside a savepoint so optional sparse failures do not poison canonical SQL transactions.
- PostgreSQL `ANALYZE` after rebuild.
- `sparse_knowledge` outbox target and worker target isolation.
- optional LLM semantic reranker using the existing per-user AI Provider; timeout/error fallback to Feature Ranker.

Representative 5000-Claim benchmarks:

```text
SQLite reference p95   423.94 ms -> FTS5 10.58 ms   (~40.07x)
PostgreSQL reference   407.20 ms -> FTS  29.03 ms   (~14.03x)
parity                 true
```

## Stage 6 current status

Stage 6 has started in default-off Shadow mode. Product graph results still come only from `SqlGraphStore`.

Neo4j current decision: **Hold / continue Shadow, do not enter Stage 7**.

- optional `neo4j>=6.3,<7`; not a default runtime dependency.
- `graph-shadow` Docker Compose profile; default deployment does not start Neo4j.
- fixed parameterized Cypher only; no Text2Cypher.
- rebuildable per-user projection; source delete; health; outbox target isolation.
- projection intentionally excludes Claim statement, Unit text, Evidence excerpt and document body/title.
- Association V2 records only aggregate Shadow diff; Neo4j never changes product ranking/output.
- synthetic 1000/5000 Claim graphs reached 100% ID/path/score parity with SQL, zero cross-user hits and zero forbidden raw properties.
- 5000 Claim / ~10k relation benchmark with 30 anchors:
  - direct p95: SQL 23.71 ms / Neo4j 25.77 ms
  - shared p95: SQL 23.09 ms / Neo4j 16.74 ms
  - combined p95: SQL 33.97 ms / Neo4j 19.20 ms (~1.77x)
- mixed query-shape performance plus unfinished real-data/lag/backup/resource/monitoring gates means `NEO4J_GRAPH_ENABLED` must remain false.

Graphiti current status:

- optional `graphiti-core==0.30.x` spike only.
- verified against 0.30.1 API; old high-level `delete_group()` assumption was removed.
- telemetry forced off before initialization.
- raw episode storage disabled.
- Claim input restricted to current-user confirmed/active/current/evidenced Claims.
- temporal input restricted to reviewed `confirmed`, `superseded`, `expired` MemoryDeclaration history.
- staged conflicts, ignored/inaccurate declarations, foreign-user data and raw conversation transcripts are excluded.
- real external-provider Graphiti ingestion/search/cost evaluation is still pending; no real user memories were sent during this Stage 6 slice.

## Test evidence

After Stage 6 changes:

```text
Stage 6 contract tests:               8 passed
real temporary Neo4j integration:     2 passed
Stage 0-6 knowledge regression:       70 passed, 2 skipped
Association V2 explicit Recall@5:     1.0
Association V2 implicit Recall@5:     1.0
cross-user probe:                     0
source-deletion residual probe:       0
unsupported display probe:            0
negative false-positive probe:        0
```

The two generic-suite skips are optional external-database integration gates; the Neo4j integration was separately run with explicit credentials and passed.

A disposable Neo4j 5.26-community instance was removed after testing. A 5000-Claim snapshot showed roughly 714 MiB process memory and 524 MiB `/data`; treat this only as a Stage 6 operational-cost signal, not production capacity planning.

## SHA256 inventory of key Stage 5/6 recovery files

```text
98968ceb1e7d3fe83603e3a3563eb461ad1b97b4a74acb23546bf617228888f1  backend/app/services/sparse_knowledge_index.py
f46dd95c7c89b86b13bc89a0e8ec27d458d9bad115e1f8d0d2f05fa826a21d81  backend/app/services/association_reranker_service.py
58505351ede956fad4eeb2b5766d8b484d349b011d8a07851205b52aed4538fd  backend/app/services/knowledge_projection_service.py
d1cf27c63c29b54d77149f93c7888e7762779b1ef8c71f1a1b05d662ab425dd2  backend/app/services/knowledge_projection_worker.py
cda1495a5a8fc6defd68d3780621561bb74636796ef2f662c7088130b31d3742  backend/app/services/association_v2_service.py
43534f2d8a2d97970f0005ea23371669aacdd15e99ba1f154cfb1facd6c71eb2  backend/app/services/graph_store/neo4j_store.py
03ea427a335b140bd3b35cdadcd823722051549496d9cfabedb2d50d84087be8  backend/app/services/graph_shadow_service.py
8d687193ac23876fe736470095ca758bc660a2a15e2e140d7be4a9d94b7906fa  backend/app/services/graphiti_shadow_service.py
19d7459d8270ac3faab2a5483db25c543fbbafac09a5f1b34464bed19ca5e005  backend/evaluate_sparse_knowledge.py
b17d2e32c3ab368f20b5042569ed8bbb465c07bdb2831cd594e49ed5414eeeef  backend/evaluate_graph_shadow.py
45e18a001ef93eea4405881e6ce05d73e962807f473cb03360f806c640e2f791  backend/tests/test_graph_shadow_stage6.py
54529a3a4ddba7bb530f851bad1fd502580f92f08524ea8c7e0eb775ec4e19e9  backend/tests/test_neo4j_shadow_integration.py
01da43590f90874eeb87f52f8a3726297253c254b3db222972be4dca56c1adc1  docs/updates/2026/2026-09-03_mnemox-v2-stage5-sparse.md
ae53d448fc2872a7b9c1f9047e3fb0b68b1e711888954f235c7f05019db0e2df  docs/updates/2026/2026-09-03_mnemox-v2-stage6-shadow.md
9f7daa4e641e258751a408abac93398060470e175f8b3dd3aa646995f0572b9b  docs/superpowers/specs/2026-09-03-mnemox-v2-stage6-neo4j-shadow-hold.md
```

## Shared hooks that must be reconstructed onto a clean Knowledge V2 branch

Do not blindly copy the dirty checkout versions of these shared files. Reapply only the Knowledge V2 deltas after establishing a clean Stage 0-4 closure:

```text
backend/app/config.py
backend/app/main.py
backend/app/routers/knowledge.py
backend/app/models/knowledge.py
backend/app/ai/* provider capabilities required by the reranker
backend/requirements-spike.txt
docker-compose.yml
.env.example
backend/env.example
docs/README.md
docs/progress.md
docs/roadmap.md
docs/technical.md
```

Also include Stage 0-3 migrations/services/tests before treating the reconstructed branch as runnable.

## Safe reconstruction order

1. Start from a clean branch containing the complete Stage 0-4 Knowledge V2 closure, not only `ac12ea5`.
2. Reapply Stage 5 sparse/reranker/projection files and shared config/router/main hooks.
3. Run Stage 0-5 regression and sparse SQLite/PostgreSQL benchmarks.
4. Create a real Stage 5 merge-ready checkpoint.
5. Reapply Stage 6 Shadow-only files and optional dependency/profile hooks.
6. Keep `NEO4J_GRAPH_ENABLED=false` and `GRAPHITI_ENABLED=false`.
7. Run Stage 6 contract tests, disposable Neo4j integration and `evaluate_graph_shadow.py`.
8. Only after real anonymous graph, projection-lag and operational gates are complete should Stage 6 produce a final Go/No-Go ADR.

This manifest exists specifically to prevent the historically dirty VPS worktree from being mistaken for a clean Git history checkpoint.
