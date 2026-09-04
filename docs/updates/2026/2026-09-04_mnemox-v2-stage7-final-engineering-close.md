# 2026-09-04 — Mnemox V2 Stage 7 Final Engineering Close

## Status

**Stage 7 engineering implementation is complete.**

This statement means the planned graph-domain contract, Optional Neo4j runtime, graph-native product slices, Graphiti Temporal experiment, deployment boundary, real database gates, regression evidence and architecture documentation are complete.

It does **not** mean real-user product quality has been proven. Real Chinese/English technical-note evaluation is intentionally the next WebUI dogfooding phase.

---

## Completed architecture

```text
SQL / PostgreSQL / SQLite
  = Canonical Knowledge + Temporal Truth

Chroma
  = rebuildable dense projection

Sparse FTS
  = rebuildable lexical projection

GraphStore
  = storage-neutral graph capability boundary

SqlGraphStore
  = default graph backend

Neo4jGraphStore
  = optional server graph execution backend

Knowledge/Learning Path
  = first graph-native product capability

Explainable Multi-hop Association
  = post-ranking, presentation-safe optional explanation

Graphiti Temporal Slice
  = experimental reviewed temporal projection
```

Default product traffic remains SQL-first.

---

## Stage 7 capabilities completed

### Graph foundation

- Graph Domain contract;
- canonical relation direction vs query traversal direction;
- storage-neutral Graph DTOs;
- `GraphStore.find_concept_paths(...)` capability boundary;
- no generic SQL BFS added merely for parity.

### Optional Neo4j Runtime

- explicit `GRAPH_BACKEND=sql|neo4j`;
- SQL default;
- missing Neo4j credentials fail closed;
- Neo4j projection/rebuild lifecycle;
- initialization / lag / caught-up readiness;
- deterministic percentage/user canary rollout;
- request-scoped Neo4j -> SQL fallback for compatible read semantics;
- stale projection gate;
- real Neo4j parity and isolation validation.

### Knowledge / Learning Path V1

- bounded graph-native Concept path traversal;
- canonical direction semantics;
- simple-path/cycle protection;
- deterministic ordering;
- learner mastery/evidence SQL overlay;
- ConceptEdge provenance/evidence SQL overlay;
- graph result SQL rehydration;
- authenticated feature-gated API;
- real Neo4j integration.

### Explainable Multi-hop Association V1

- independent default-off feature flag;
- enrichment after candidate ranking;
- does not change rank/score;
- graph topology discovery + SQL provenance validation;
- presentation-safe path representation;
- no SQL/Neo4j internal IDs or Cypher in the new explanation surface;
- no valid path -> no fabricated explanation.

### Graphiti Temporal / Episodic Slice

- reviewed `MemoryDeclaration` only;
- staged conflict/raw chat excluded;
- model-free Graphiti BM25 path;
- current/as-of temporal lookup;
- supersede/invalidation;
- cross-user isolation;
- delete/rebuild;
- SQL rehydrate;
- fixed safe API failures;
- real Graphiti 0.30.x + Neo4j integration;
- zero external LLM/embedding/reranker calls in this bounded slice.

---

## Final regression evidence

### Stage 0–7 Knowledge / Temporal wide regression

```text
149 passed, 1 warning
```

The suite includes:

- Knowledge Stage 0;
- source lifecycle;
- extraction;
- Entity Resolution;
- knowledge projection;
- Sparse Knowledge;
- Association V2;
- Explainable Multi-hop;
- GraphStore contract;
- rollout/readiness;
- Neo4j projection lifecycle;
- Stage 6 graph shadow safety;
- Knowledge Path/API;
- Graphiti Temporal service/API;
- SQL memory declarations / temporal lifecycle.

The only warning is the existing third-party Graphiti Pydantic v2 class-based config deprecation.

### Real graph database gates

Explicitly run against the local disposable Neo4j 5.26 test service; no skip used as acceptance:

```text
Neo4j Shadow + Knowledge Path      4 passed
Stage 6 Graphiti integration      1 passed
Stage 7 Graphiti Temporal         1 passed
------------------------------------------
Real graph database gates         6 passed
```

### Association / schema / contract supplementary gate

```text
35 passed
```

Covers Association V1, schema migration and GraphStore contract.

### Frontend

```text
27 test files passed
93 tests passed
TypeScript/Vite production build passed
ESLint passed with max-warnings=0
```

### Python static compile

Stage 7 core services compile successfully:

- `graphiti_temporal_service.py`
- `knowledge_path_service.py`
- `association_explanation_service.py`

---

## Deployment boundary verified

Docker Compose default service set:

```text
db
backend
frontend
```

With optional graph profile:

```text
db
backend
frontend
neo4j
```

Therefore:

- default open-source/server deployment does not require Neo4j;
- `--profile graph` enables the optional graph server;
- `graph-shadow` remains a compatibility alias for the Stage 6 workflow;
- `GRAPH_BACKEND=sql` remains default;
- `GRAPHITI_ENABLED=false` remains default;
- desktop/local product behavior continues to have the SQL path.

---

## Benchmark decisions preserved

### Neo4j

Stage 6 proved Neo4j did not justify a mandatory runtime migration for the existing query mix. Stage 7 therefore used it only where topology is genuinely useful and kept rollout/fallback/rebuild boundaries.

### Graphiti

Stage 7 bounded temporal benchmark:

```text
60 temporal declarations
  SQL correctness       1.0
  Graphiti correctness  1.0
  SQL p95               4.766 ms
  Graphiti p95          192.204 ms
  Graphiti rebuild      2305.701 ms

300 temporal declarations
  SQL correctness       1.0
  Graphiti correctness  1.0
  SQL p95               2.921 ms
  Graphiti p95          138.552 ms
  Graphiti rebuild      9302.495 ms
```

Cross-user leakage and external model calls are zero in the bounded slice.

Decision:

```text
MemoryDeclaration SQL = Canonical/default
Graphiti              = Experimental/default-off
```

---

## Architecture / interview material

Added:

`docs/superpowers/specs/2026-09-04-mnemox-v2-stage7-architecture-story.md`

It records:

- why SQL came first;
- why GraphStore preceded Neo4j;
- why Stage 6 was NO-GO;
- why Stage 7 reopened an Optional Neo4j backend without contradicting Stage 6;
- why Knowledge Path is graph-native;
- why generic SQL BFS was intentionally avoided;
- how Explainable Multi-hop is separated from ranking;
- why Graphiti is not `MemoryDeclaration`;
- real benchmark trade-offs;
- final deployment topology;
- a concise interview narrative and follow-up questions.

---

## Recovery policy

The active checkout still contains historical dirty/untracked work from multiple earlier stages. It is the authoritative source but is **not a clean merge-ready branch**.

Stage 7 used recovery-only GitHub checkpoints after independent modules:

```text
backup/stage7-graph-foundation-20260904
backup/stage7-readiness-20260904
backup/stage7-knowledge-path-20260904
backup/stage7-explainable-multihop-20260904
backup/stage7-graphiti-temporal-20260904
```

A final Stage 7 engineering-close recovery checkpoint is created after the final diff/hash verification.

---

## Next phase: cloud WebUI dogfooding

Do not continue adding Stage 7 infrastructure before collecting real product evidence.

Next objective:

```text
cloud WebUI
  -> user imports own technical notes
  -> extraction/review
  -> Claim / Concept / Relation
  -> Association / Knowledge Path / Explanation
  -> temporal behavior when relevant
  -> human evaluation + real latency/fallback observations
```

The real-note evaluation should separately record:

- Chinese / English / mixed-language cases;
- unsupported/forced Association rate;
- Claim grounding quality;
- Concept/relation review corrections;
- Knowledge Path usefulness;
- explanation usefulness;
- no-path cases;
- projection/fallback behavior;
- real data scale and latency.

This is intentionally product validation, not a retroactive rewrite of Stage 7 synthetic engineering evidence.
