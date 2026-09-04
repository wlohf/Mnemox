# 2026-09-04 — Mnemox V2 Stage 7 Graphiti Temporal Slice

## Scope

This checkpoint completes the bounded Stage 7 Graphiti Temporal / Episodic vertical slice without changing SQL temporal truth.

Implemented:

- reviewed `MemoryDeclaration` -> deterministic Graphiti temporal projection;
- current and historical `as_of` lookup;
- supersede / invalidation handling through SQL validity boundaries;
- staged conflict exclusion;
- cross-user group isolation;
- explicit group delete + rebuild;
- SQL rehydrate before product response;
- authenticated experimental status/rebuild/query API;
- fail-closed model clients;
- real Graphiti 0.30.x + Neo4j integration;
- SQL Temporal vs Graphiti Temporal benchmark.

Not implemented by design:

- raw chat ingestion;
- selected conversation episodes;
- Graphiti-owned memory truth;
- automatic conflict approval;
- incremental Graphiti outbox;
- default production enablement.

## Architecture

```text
SQL MemoryDeclaration
  (Canonical temporal truth)
          |
          | explicit rebuild
          v
Graphiti Temporal Projection
  - per-user group
  - temporal RELATES_TO edges
  - BM25-only search
          |
          | declaration IDs only
          v
SQL ownership/review/valid-time rehydrate
          |
          v
Experimental API response
```

`GRAPHITI_ENABLED=false` remains the default feature gate. `GRAPHITI_SHADOW` remains a separate comparison flag.

## Product/API boundary

Authenticated endpoints under `/api/memory`:

```text
GET  /temporal-graph/status
POST /temporal-graph/rebuild
POST /temporal-graph/query
```

Failure policy:

- disabled -> 409;
- unavailable Graphiti/Neo4j -> fixed 503;
- raw Neo4j/Graphiti errors never reach the client;
- SQL memory features continue operating independently.

## Model-free storage detail

Graphiti 0.30.x saves Entity node and Entity edge vector properties through Neo4j vector procedures. Neo4j rejects `null` vectors even when the Stage 7 query path uses BM25 only.

The Temporal Slice therefore writes a fixed zero-vector using Graphiti's configured embedding dimension. This vector is only a structural placeholder:

```text
external LLM calls       = 0
external embedding calls = 0
external reranker calls  = 0
configured model cost    = 0
```

The installed Graphiti model clients fail closed if any of those model paths are accidentally invoked.

## Correctness / integration evidence

Focused SQL/Memory/Graphiti regression:

```text
40 passed, 1 warning
```

Real Stage 6 Graphiti integration:

```text
1 passed, 1 warning
```

Real Stage 7 Temporal Slice integration:

```text
1 passed, 1 warning
```

The Stage 7 real integration verifies:

```text
Sep 05 -> Tool Calling
Sep 15 -> Agent Runtime
Sep 25 -> LangGraph
```

and also verifies:

- staged declaration excluded;
- foreign-user temporal fact excluded;
- explicit delete makes projection not caught up;
- rebuild restores caught-up state;
- SQL data remains authoritative throughout.

The only warning is the existing third-party Graphiti Pydantic v2 class-based config deprecation.

## Benchmark

Command:

```text
PYTHONPATH=. venv/bin/python evaluate_graphiti_temporal_slice.py \
  --neo4j-uri <test-uri> \
  --neo4j-user <test-user> \
  --neo4j-password <test-password> \
  --sizes 20,100 \
  --query-keys 10
```

### 20 fact keys / 60 temporal declarations

```text
queries                 30
SQL correctness         1.0
Graphiti correctness    1.0
SQL p50                 1.847 ms
SQL p95                 4.766 ms
Graphiti p50            135.356 ms
Graphiti p95            192.204 ms
Graphiti rebuild        2305.701 ms
delete                   67.348 ms
recovery rebuild        1675.524 ms
```

### 100 fact keys / 300 temporal declarations

```text
queries                 30
SQL correctness         1.0
Graphiti correctness    1.0
SQL p50                 1.862 ms
SQL p95                 2.921 ms
Graphiti p50            125.496 ms
Graphiti p95            138.552 ms
Graphiti rebuild        9302.495 ms
delete                  147.181 ms
recovery rebuild        8334.713 ms
```

Both cases:

```text
cross-user leakage      0
external model calls    0
embedding model calls   0
configured model cost   0
raw episode storage     false
recovery correctness    true
```

## Decision

Graphiti is **not promoted to the default runtime**.

The important result is not that Graphiti failed correctness; correctness is 1.0 in this bounded test. The result is that Temporal SQL is much faster and operationally simpler for the current reviewed declaration use case.

Graphiti remains useful in Mnemox as:

1. a real Temporal/Episodic architecture experiment;
2. a place to evaluate future episodic/multi-fact temporal graph queries that are awkward in relational SQL;
3. a portfolio/interview case showing evidence-based technology selection rather than framework-driven migration.

Real Chinese/bilingual human evaluation is intentionally deferred until the post-Stage-7 WebUI dogfooding step, where the user will import their own technical notes. No fake "real user" conclusion is recorded here.
