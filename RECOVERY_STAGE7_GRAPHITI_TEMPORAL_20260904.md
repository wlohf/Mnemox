# Recovery checkpoint — Stage 7 Graphiti Temporal Slice — 2026-09-04

> Recovery-only branch. **Not merge-ready.**
>
> The authoritative working copy remains `/home/cloudcli/projects/mnemox`, whose checkout contains historical dirty/untracked work from multiple earlier stages. This branch preserves the new Stage 7 Temporal Slice core plus exact recovery metadata; it must not be treated as a clean full snapshot of every shared-file edit.

## Scope completed

- Reviewed SQL `MemoryDeclaration` -> deterministic Graphiti temporal projection.
- Model-free BM25 current/as-of search.
- Supersede / invalidation via SQL valid-time boundaries.
- Staged-conflict exclusion and cross-user group isolation.
- SQL rehydrate before product response.
- Explicit delete + rebuild + caught-up status.
- Experimental authenticated API hooks under `/api/memory/temporal-graph/*` behind `GRAPHITI_ENABLED=false` by default.
- Graphiti 0.30.x / Neo4j real integration.
- SQL Temporal vs Graphiti Temporal benchmark.
- Docker Compose optional `graph` profile added while retaining `graph-shadow` compatibility alias in the active checkout.

## Test evidence

Focused SQL/Memory/Graphiti regression:

`40 passed, 1 warning`

Real Stage 6 Graphiti integration:

`1 passed, 1 warning`

Real Stage 7 Graphiti Temporal integration:

`1 passed, 1 warning`

The only warning is the pre-existing third-party Graphiti Pydantic v2 class-based config deprecation.

## Benchmark evidence

20 fact keys / 60 temporal declarations:

- SQL correctness: `1.0`
- Graphiti correctness: `1.0`
- SQL p95: `4.766 ms`
- Graphiti p95: `192.204 ms`
- Graphiti rebuild: `2305.701 ms`

100 fact keys / 300 temporal declarations:

- SQL correctness: `1.0`
- Graphiti correctness: `1.0`
- SQL p95: `2.921 ms`
- Graphiti p95: `138.552 ms`
- Graphiti rebuild: `9302.495 ms`

Both cases:

- cross-user leakage: `0`
- external LLM calls: `0`
- external embedding calls: `0`
- configured model cost: `0`
- delete -> not caught-up -> rebuild recovery: verified

Decision: Graphiti remains Experimental/default-off; SQL `MemoryDeclaration` remains temporal Canonical.

## SHA256 inventory from the authoritative active checkout

- `backend/app/services/graphiti_temporal_service.py` `eca40370a163c55cfe212a9bb4fb6a7ab573118701362db9369525d9ca3174b0`
- `backend/app/routers/memory.py` `ff37927b97987a52954bd89dd987f1f7e76a031b3e99bb9bf6c46454fd803b11`
- `backend/tests/test_graphiti_temporal_service.py` `65e68f87db8909418c9d818c52fc10920440cad40f0a55d451192323f61d4312`
- `backend/tests/test_graphiti_temporal_api.py` `1ca23839ef637b02939fe8eeae90ea620fcab0658389dd5923486a20544794cd`
- `backend/tests/test_graphiti_temporal_integration.py` `18531c77e2dafb202b9b586a4035161bbf0b81b32a356cd44aa5fccf379cde41`
- `backend/evaluate_graphiti_temporal_slice.py` `d5412a0c00607ded34fff09dc8ae2f8f6378b18dfbf1d87ae42aaaf27faa17c9`
- `docs/superpowers/specs/2026-09-04-mnemox-v2-graphiti-temporal-slice-contract.md` `cfc51ee86bf141b6e1f63c1e104f862ad07efbba27cfedffd6a7772af090f9b0`
- `docs/updates/2026/2026-09-04_mnemox-v2-stage7-graphiti-temporal-slice.md` `d322df370bbb0db51798850245985429a2a8c1c5189c55fc0f61667d709b9438`

## Shared-file hooks documented but not represented as a clean branch snapshot

The active checkout also contains Stage 7 edits to:

- `backend/app/routers/memory.py`
- `docker-compose.yml`
- `docs/progress.md`
- `docs/roadmap.md`
- `docs/technical.md`
- `docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md`

These files already contain unrelated historical work in the active checkout, so this recovery branch intentionally does not claim to be a clean merge-ready representation of them.
