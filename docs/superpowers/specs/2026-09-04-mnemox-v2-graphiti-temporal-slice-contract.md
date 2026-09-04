# Mnemox V2 Stage 7 — Graphiti Temporal / Episodic Slice Contract

> Date: 2026-09-04  
> Status: implemented / verified  
> Depends on: SQL `MemoryDeclaration` temporal lifecycle + Stage 6 Graphiti shadow evidence

## 1. Why this slice exists

Stage 6 proved that Graphiti can reproduce the current SQL temporal lookup with correct user isolation, but it did not prove enough product/runtime benefit to replace SQL. Stage 7 therefore does **not** turn Graphiti into the memory source of truth.

This slice answers a narrower engineering/product question:

> Can an optional temporal graph make reviewed fact history and episodic evolution easier to query and explain, while SQL continues to own review, correction, conflicts, validity and deletion?

The first concrete scenario is a changing learning focus:

```text
Sep 01  learning_focus = Tool Calling
Sep 10  learning_focus = Agent Runtime
Sep 20  learning_focus = LangGraph
```

The system must answer both:

```text
What is the current learning focus?
What was the learning focus on Sep 05 / Sep 15?
```

without allowing Graphiti to invent or approve facts.

---

## 2. Canonical boundary

SQL `MemoryDeclaration` remains authoritative for:

- fact identity (`fact_key`);
- `confirmed / staged / superseded / ignored / inaccurate / expired` review state;
- `valid_from / valid_to`;
- conflicts and human approval;
- correction / supersede relationships;
- deletion and privacy lifecycle.

Graphiti is a **rebuildable temporal projection** only.

Graphiti must never:

- ingest staged conflict candidates;
- become the only copy of a memory fact;
- auto-approve a fact extracted from chat;
- update SQL learner state or memory truth;
- bypass SQL ownership filters;
- return raw graph records directly to the API.

---

## 3. Input boundary

Stage 7 V1 ingests only reviewed temporal declarations:

```text
review_status IN (confirmed, superseded, expired)
```

Selected conversations and arbitrary raw chat episodes are **out of scope**.

The projection is deterministic and model-free:

- no LLM call;
- no embedding call;
- no cross-encoder call;
- no Graphiti telemetry;
- no raw chat/document ingestion.

A reviewed declaration becomes one Graphiti temporal relation whose episode provenance points back to the SQL declaration ID.

---

## 4. Temporal projection shape

For one SQL declaration:

```text
subject / user
    -- predicate / fact_key / temporal edge -->
logical fact slot
```

The edge stores only the reviewed temporal fact needed by the experimental projection:

- deterministic group ID scoped to one user;
- predicate / fact key;
- reviewed value in the Graphiti fact text;
- SQL declaration episode ID;
- `valid_at = valid_from`;
- `invalid_at = valid_to` when superseded/closed;
- `expired_at` only for an explicitly expired fact when applicable;
- reference time from SQL `observed_at` / `valid_from`.

The graph is disposable. Rebuild always starts from SQL.

---

## 5. Query contract

The experimental product query supports:

- free-text temporal lookup;
- optional `fact_key` narrowing;
- current lookup (`as_of = now`);
- historical `as_of` lookup;
- bounded result count.

Flow:

```text
API query
  -> Graphiti BM25 temporal edge search
  -> group + valid-time filter
  -> SQL declaration IDs only
  -> Canonical SQL rehydrate + visibility revalidation
  -> product response
```

If Graphiti returns a declaration that no longer matches current SQL ownership/review/lifecycle, the result is rejected rather than partially trusted.

The API never returns Graphiti UUIDs, Neo4j node IDs, Cypher, embeddings or driver errors.

---

## 6. Lifecycle contract

V1 lifecycle deliberately prefers correctness over incremental write complexity.

### Rebuild

```text
SQL reviewed declarations
  -> delete this user's Graphiti group
  -> rebuild deterministic temporal graph
```

### Correction / supersede

SQL closes the old declaration and opens the new one. A rebuild materializes both historical validity intervals.

### Invalidation / expiration

The SQL validity boundary remains canonical. Rebuild updates the graph projection accordingly.

### Delete

Deleting the user's projected group removes all Graphiti temporal state. Rebuild recreates only what still exists in SQL.

No incremental Graphiti outbox is introduced in Stage 7 V1. This is an experimental slice, not a second production write path.

---

## 7. Feature flag and API boundary

Reuse the existing default-off flag:

```text
GRAPHITI_ENABLED=false
```

`GRAPHITI_SHADOW` remains a comparison flag and does not expose the product endpoint.

Authenticated experimental endpoints:

```text
POST /api/memory/temporal-graph/rebuild
POST /api/memory/temporal-graph/query
GET  /api/memory/temporal-graph/status
```

The endpoint is available only when `GRAPHITI_ENABLED=true`.

Failure semantics:

- disabled -> HTTP 409;
- Graphiti unavailable -> HTTP 503 with fixed safe detail;
- no temporal result -> successful empty result;
- SQL remains usable regardless of Graphiti failure.

---

## 8. Benchmark / comparison contract

The Stage 7 comparison records both SQL Temporal and Graphiti Temporal behavior.

Required dimensions:

- current-fact correctness;
- as-of correctness;
- supersede / invalidation correctness;
- cross-user leakage count;
- rebuild latency;
- search p50 / p95;
- external LLM calls;
- embedding calls;
- configured model cost;
- failure recovery;
- deletion / rebuild behavior;
- implementation complexity notes.

V1 is intentionally model-free, therefore:

```text
LLM calls = 0
embedding calls = 0
configured model cost = 0
```

This does **not** prove that all Graphiti use cases are free; it only describes this bounded deterministic slice.

---

## 9. Acceptance criteria

Before Stage 7 Graphiti is considered complete:

- current query returns only the current reviewed declaration;
- historical as-of query returns the declaration active at that time;
- superseded / expired facts are not returned outside their valid interval;
- staged conflicts never enter the graph projection;
- correction/supersede is represented through SQL validity boundaries;
- cross-user leakage = 0;
- group delete + rebuild works;
- Graphiti/Neo4j failure does not poison SQL sessions;
- query results are rehydrated from SQL before returning;
- no raw driver/query details leak to clients;
- real Graphiti + Neo4j integration runs with zero model calls;
- Stage 0–7 Knowledge/Memory regression remains green;
- Graphiti remains default-off and experimental.

---

## 10. Architecture decision

Verified Stage 7 benchmark snapshot:

```text
60 temporal declarations:
  SQL correctness       1.0
  Graphiti correctness  1.0
  SQL p95               4.766 ms
  Graphiti p95          192.204 ms
  Graphiti rebuild      2305.701 ms

300 temporal declarations:
  SQL correctness       1.0
  Graphiti correctness  1.0
  SQL p95               2.921 ms
  Graphiti p95          138.552 ms
  Graphiti rebuild      9302.495 ms

cross-user leakage      0
external LLM calls      0
external embedding calls 0
configured model cost   0
```

Graphiti 0.30.x requires non-null vector properties when saving Entity nodes/edges on Neo4j even for BM25-only retrieval. Stage 7 therefore stores a fixed local zero-vector placeholder with Graphiti's configured embedding dimension. This is structural storage data, not a model-generated embedding; model clients remain fail-closed and the integration test proves no external embedding/LLM/reranker call occurs.

The desired final Stage 7 story is:

```text
SQL MemoryDeclaration
      = temporal truth

Graphiti Temporal Slice
      = optional temporal projection / experiment
```

If later dogfooding shows that temporal graph queries solve a real product problem that SQL cannot express cleanly, Graphiti can be promoted behind a stronger projection lifecycle. If not, the experiment remains a documented NO-GO/limited-use result without corrupting the product architecture.
