# Recovery checkpoint — Stage 7 Final Engineering Close — 2026-09-04

> Recovery-only branch. **Not merge-ready.**
>
> The authoritative active checkout remains `/home/cloudcli/projects/mnemox`, which contains historical dirty/untracked work from multiple earlier stages. This branch preserves final Stage 7 recovery evidence and selected new files; it must not be treated as a clean full snapshot of all shared-file edits.

## Stage 7 engineering status

Stage 7 engineering implementation is complete:

- Graph Domain / GraphStore contract;
- Optional Neo4j Runtime selector/readiness/fallback/rollout;
- Knowledge/Learning Path V1;
- Explainable Multi-hop Association V1;
- Graphiti Temporal/Episodic Slice;
- default vs optional graph Compose boundary;
- real Neo4j/Graphiti database acceptance;
- frontend test/build/lint acceptance;
- Architecture Story / interview rationale.

SQL/PostgreSQL/SQLite remains Canonical and the default runtime. Neo4j remains optional. Graphiti remains Experimental/default-off.

## Final regression evidence

Stage 0–7 Knowledge/Temporal wide regression:

`149 passed, 1 warning`

Real graph database gates, explicitly executed rather than accepted as skips:

- Neo4j Shadow + Knowledge Path: `4 passed`
- Stage 6 Graphiti integration: `1 passed`
- Stage 7 Graphiti Temporal integration: `1 passed`
- total real graph database gates: `6 passed`

Association V1 + schema migration + GraphStore supplementary gate:

`35 passed`

Frontend:

- `27` test files passed
- `93` tests passed
- TypeScript/Vite production build passed
- ESLint passed with `--max-warnings 0`

Docker Compose:

- default services: `db`, `backend`, `frontend`
- `--profile graph`: additionally `neo4j`
- local disposable Neo4j 5.26 service observed healthy

`git diff --check`:

- no whitespace errors
- existing PowerShell LF/CRLF warning only

## Graphiti benchmark decision

60 temporal declarations:

- SQL correctness `1.0`
- Graphiti correctness `1.0`
- SQL p95 `4.766 ms`
- Graphiti p95 `192.204 ms`
- Graphiti rebuild `2305.701 ms`

300 temporal declarations:

- SQL correctness `1.0`
- Graphiti correctness `1.0`
- SQL p95 `2.921 ms`
- Graphiti p95 `138.552 ms`
- Graphiti rebuild `9302.495 ms`

Cross-user leakage and external model calls are zero in this bounded slice.

Decision: `MemoryDeclaration` SQL remains temporal truth/default; Graphiti stays Experimental/default-off.

## Selected final hashes from authoritative active checkout

- `backend/app/services/graphiti_temporal_service.py` `bb41de8bbf9b2485808285af8b5d794eeaef54df7c68dc038c72f39116c38d23`
- `docs/superpowers/specs/2026-09-04-mnemox-v2-stage7-architecture-story.md` `f3a1926b5e56441bebb3e526d8dd6cb2b118208ae4b7a5a303d29854251346c8`
- `docs/updates/2026/2026-09-04_mnemox-v2-stage7-final-engineering-close.md` `e213a9b25ff2640a309bb2cf2c303d3a361234572c5e4e83bbb022f76bb06b58`

## Prior Stage 7 checkpoints

- `backup/stage7-graph-foundation-20260904`
- `backup/stage7-readiness-20260904`
- `backup/stage7-knowledge-path-20260904`
- `backup/stage7-explainable-multihop-20260904`
- `backup/stage7-graphiti-temporal-20260904`

## Shared-file edits documented but not represented as a clean merge-ready snapshot

The active checkout contains Stage 7 edits across shared files including:

- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/routers/knowledge.py`
- `backend/app/routers/memory.py`
- `backend/app/services/association_v2_service.py`
- `backend/app/services/graph_store/*`
- `backend/app/services/knowledge_projection_*`
- `docker-compose.yml`
- `docs/progress.md`
- `docs/roadmap.md`
- `docs/technical.md`
- the Stage 7 implementation plan and ADR/update documents.

Those files already contain unrelated historical changes in the active checkout, so this recovery branch intentionally does not claim to be a clean full Stage 7 branch.

## Next phase

The next work item is **cloud WebUI dogfooding**, not more Stage 7 infrastructure:

- deploy/provide a cloud-accessible test UI;
- let the user import their own Chinese/English technical notes;
- observe Claim/Concept/Relation/Association/Knowledge Path/Explanation/Temporal behavior on real data;
- record human evaluation separately from Stage 7 synthetic engineering acceptance.
