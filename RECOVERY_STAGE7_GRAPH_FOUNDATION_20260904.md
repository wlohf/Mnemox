# Mnemox Stage 7 Graph Foundation Recovery Checkpoint

> Created: 2026-09-04
> Branch: `backup/stage7-graph-foundation-20260904`
> Parent recovery branch: `backup/stage5-stage6-recovery-20260903`
> Status: **recovery-only / non-merge-ready**

## Purpose

This branch preserves the verified Stage 7 graph-foundation checkpoint so later graph/backend work can recover this exact milestone if a regression appears.

It must **not** be merged wholesale into `main`. The active VPS checkout is historically dirty and contains unrelated work. Shared files are therefore treated as recovery snapshots, not clean feature commits.

## Authoritative local source

```text
workspace: /home/cloudcli/projects/mnemox
committed HEAD: 97036f490422f06fff3a5bec22232ef1ebe91c4b
working tree: dirty, containing Stage 0-7 and unrelated historical changes
```

The active checkout was intentionally not staged, reset, stashed, cleaned, or committed while creating this recovery branch.

## Stage 7 checkpoint scope

Completed in this checkpoint:

- Graph domain contract frozen: node/edge responsibilities, canonical relation direction, evidence/review/lifecycle/source-version/delete/user-isolation rules.
- Storage-neutral path DTOs: `GraphNodeRef`, `GraphEdgeRef`, `GraphPath`, `TraversalDirection`.
- `GraphHit.graph_path` added while keeping the legacy compact path for Association V2 compatibility.
- SQL backend explicitly refuses generic graph-native path search instead of growing into a custom shortest-path/BFS engine.
- Explicit `GRAPH_BACKEND=sql|neo4j` selector; SQL remains default and canonical.
- Neo4j runtime selection is coupled to the Neo4j projection/outbox worker so query cutover cannot silently run against an unmaintained graph.
- Request-scoped `FallbackGraphStore`: read queries may fall back Neo4j -> SQL; projection operations such as rebuild/delete must fail explicitly rather than fake success.
- Fallback diagnostics retain backend/error type/latency but not raw exception message/query/body.
- Health semantics separate primary-backend health from `serving_ok` through SQL fallback.
- Stage 6 Shadow/benchmark history remains intact; this does not rewrite the Stage 6 default-runtime NO-GO decision.

## Verification evidence

```text
Stage 7 graph contract/fallback + Stage 6 regression:
33 passed, 2 skipped, 1 warning
```

The two skips are optional real-Neo4j integration gates in the current local environment, not assertion failures.

`git diff --check` passed for the current worktree; the only emitted message was the pre-existing PowerShell LF/CRLF warning for `scripts/publish_desktop_release.ps1`.

## SHA256 inventory

```text
166ec26f862d4f8c5cfe41e4b0085d612c0edf22b8f2489e1f2f57760cbe2057  .env.example
3e849a69e7807ecdaa6c483e6003b0d16ec0b7998dbdaa005d951d38289fd84a  backend/env.example
7dece22fb1dd90c084d79b666f85a01ef9bccf1922bc42fba75ce8f7a1b92b50  backend/app/config.py
56c1c7c0a13a39bae87acf6b82eb03939719221e486d89b411487f9bad786fde  backend/app/main.py
09cfe79e0a690778cd9aa6da979bace8e02869873420314105bbc97c3dab1609  backend/app/services/association_v2_service.py
602cdc4d6a04bd0e853f982ed3d75aa242d039b3910fcad85812e2c3bc6cfd40  backend/app/services/knowledge_projection_service.py
b2d1a5ccd1a3f80a37638429eef49939605ecb590453a71b51c10abc594dff7e  backend/app/services/knowledge_projection_worker.py
1883124a18e1ac95a129b5e9bb805d6b3b3813fa0a83bfdbd89c2356844777ed  backend/app/services/graph_store/base.py
86a07b8511bc6e97c9c1dcc6430cc4ff20e9f772dcced3727ac70f5bc0e7602e  backend/app/services/graph_store/__init__.py
0c146c868301c3674a5b5de1e27026adc80df48cc4383b854b60c800f7093473  backend/app/services/graph_store/factory.py
0f0a3fd46187b9e253e0c88332f7122763f25be8356edb87990e5890455b8cd5  backend/app/services/graph_store/sql_store.py
90ea8a875e41c0744e1bc44711732cbea6f98b9944d89279d1aa34dbf47b6639  backend/app/services/graph_store/neo4j_store.py
b64782760dfa6eba4da249adba304b5ce5c599cc46e25e36065337dcc79bc00c  backend/app/services/graph_store/fallback_store.py
71b1ccf2e63f99788f83c4f7b0f439d348003d0ac3a93091a10b82a6b6a38693  backend/tests/test_graph_shadow_stage6.py
b2e3ecd67b86e31914313e4aeb05df3b462ba7087fd43dfd7d52cc1791aab20a  backend/tests/test_graph_store_contract.py
b68fa3b5b2cd5e438400da343ce46b07f8500bacbce63b29e4b416370f6f90e6  docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md
db168bb9bc70791dd5bbdd860fd0eb89f2f243b4fb9763a758c9d6678ee7f122  docs/superpowers/specs/2026-09-04-mnemox-v2-graph-domain-contract.md
106afe8664361809d0718ed4e29027248cd176610a08e700c57d2512bd603568  docs/superpowers/specs/2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md
0efbbd29470a9406abcebfc1eaf34958973bfe24f93940b0d48e480caa3cd4d1  docs/superpowers/specs/2026-09-04-mnemox-v2-graph-foundation-strategy.md
4920c4ede3c96919910e8cf3efb3a17d70e13383be9fb89f1b2712cfa1e98232  docs/superpowers/specs/2026-09-04-mnemox-v2-stage6-final-go-no-go.md
a8e1a4a59c687909cfc5a9929bf923e6890a6c6f7d084cc77d77f8a83b6062d0  docs/updates/2026/2026-09-04_mnemox-v2-stage7-graph-domain-contract.md
14d7c2e84f1622258a383669c1e0474a16b8bcfc7cefa12cb82d65fefb9f1c91  docs/progress.md
6972399adf06a9b89d5f9f5a37387a2fb94e213b78a2a4fb91c899488ae26ca1  docs/roadmap.md
ad629bdc781574d40d238b62195248633a6c9fd9a7034b66ebc841f7a634dcdd  docs/technical.md
```

## Recovery rule

When recovering this milestone, prefer the files stored under `recovery/stage7_graph_foundation/` on this branch and verify their hashes against this inventory. Shared files (`config.py`, `main.py`, env examples, progress/roadmap/technical) are full recovery snapshots and may include unrelated historical dirty changes; use them as reference or selective restore sources, not as a clean merge patch.

Do not delete or rewrite the Stage 6 NO-GO/benchmark ADRs when restoring Stage 7. The intended story remains: Stage 6 rejected default runtime cutover; Stage 7 reopened Neo4j as an optional backend for graph-native capability while SQL remains canonical.
