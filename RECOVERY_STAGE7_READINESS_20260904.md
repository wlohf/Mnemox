# Mnemox Stage 7 Graph Runtime Readiness Recovery Checkpoint

> Created: 2026-09-04
> Branch: `backup/stage7-readiness-20260904`
> Parent checkpoint: `backup/stage7-graph-foundation-20260904`
> Status: **recovery-only / non-merge-ready**

## Scope

This checkpoint preserves the independent Stage 7 runtime-readiness block completed after the graph-foundation checkpoint.

Implemented behavior:

- authenticated graph runtime diagnostics are exposed through `/api/knowledge/status`;
- runtime status distinguishes `primary_ready` from `serving_ready`;
- when `GRAPH_BACKEND=neo4j`, primary readiness requires both backend connectivity and a caught-up user projection;
- caught-up means no `pending`, `processing`, `failed`, or dead-letter Neo4j projection tasks for that user;
- SQL fallback may keep `serving_ready=true` even when Neo4j primary readiness is false;
- backend misconfiguration fails closed and exposes only exception type, never raw exception message/query/body;
- no arbitrary lag-seconds threshold was introduced yet. Correctness is strict first; rollout tolerance, if any, belongs to later gray-release evidence.

## Verification

```text
38 passed, 2 skipped, 1 warning
```

Command used from `backend/`:

```text
venv/bin/python -m pytest -q \
  tests/test_graph_runtime_status.py \
  tests/test_graph_store_contract.py \
  tests/test_graph_shadow_stage6.py \
  tests/test_association_v2.py \
  tests/test_neo4j_shadow_integration.py
```

The two skipped tests are optional real-Neo4j integration gates in the current environment.

## Files in this block

Primary new implementation:

- `backend/app/services/graph_runtime_status_service.py`
- `backend/tests/test_graph_runtime_status.py`

Integration hook in the active checkout:

- `backend/app/routers/knowledge.py` imports `graph_runtime_status` and adds a `graph_runtime` field to authenticated knowledge status.

Documentation updated in the active checkout:

- `docs/roadmap.md`
- `docs/progress.md`
- `docs/technical.md`
- `docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md`
- `docs/updates/2026/2026-09-04_mnemox-v2-stage7-graph-domain-contract.md`

Because the source checkout is historically dirty, shared router/docs files are not represented as a clean merge claim. This branch is a rollback/reconstruction checkpoint, not a merge-ready feature branch.

## Design invariant

`Neo4j reachable != Neo4j ready`.

A graph projection can be connected but stale. Therefore:

```text
primary_ready = primary_health_ok AND projection_caught_up
serving_ready = selected runtime can still serve safe reads (including SQL fallback)
```

This keeps correctness and availability separate and prevents stale graph paths from being presented as healthy.
