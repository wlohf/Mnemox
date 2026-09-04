# Mnemox V2 Stage 7 — Knowledge / Learning Path Contract

> Date: 2026-09-04  
> Status: Phase 3.1 implemented and verified  
> Depends on: Graph Domain Contract + Optional Neo4j Runtime/Readiness checkpoint

## 1. Why this feature exists

Stage 6/7 has already proved that simply rewriting existing Association SQL in Cypher is not enough reason to run Neo4j. The first product feature that should justify a graph execution backend is a **bounded, explainable path query** that would otherwise push SQL toward a custom graph engine.

Knowledge / Learning Path answers one concrete question:

```text
I know / choose Concept A.
I want to reach Concept D.
What prerequisite chain connects them, and which steps am I weak on?
```

Example:

```text
Tool Calling
  -> Agent Runtime
  -> State Management
  -> Workflow
  -> LangGraph
```

Neo4j owns only the graph-native execution problem: **find the path**.

SQL remains Canonical for:

- Concept identity and display fields;
- Learner mastery / confidence / forgetting risk;
- LearnerEvidence;
- ConceptEdge provenance and ConceptSourceEvidence;
- review/lifecycle truth.

This avoids copying learner state or source excerpts into Neo4j merely to make the feature work.

---

## 2. V1 product boundary

V1 is intentionally narrow.

### Inputs

- current authenticated user;
- one or more explicit start Concept IDs;
- one target Concept ID;
- bounded `max_depth`;
- allowed Concept relation types;
- bounded result count.

### Default relation semantics

Default:

```text
relation_types = ["prerequisite_of"]
direction = outgoing
```

Canonical meaning:

```text
A prerequisite_of B
A -> B
```

Learning Path therefore walks **prerequisite -> dependent** by default.

`related_to` is symmetric. It may participate only when the caller explicitly includes it; it is an auxiliary connection and must never be presented as a prerequisite.

### Not in V1

- auto-selecting the user’s best starting Concept;
- k-shortest-path algorithms beyond a bounded result set;
- global graph optimization / PageRank / communities;
- LLM-generated missing edges;
- Text2Cypher;
- copying LearnerEvidence / excerpts into Neo4j;
- a generic SQL BFS engine.

---

## 3. Runtime / fallback policy

Knowledge Path is the first deliberately **graph-native capability**.

Therefore the fallback rule differs from Association:

```text
basic Association read
Neo4j failure -> SQL fallback

Knowledge Path
Neo4j unavailable / user outside rollout / projection stale
-> capability unavailable
```

Why:

- `SqlGraphStore` intentionally does not implement generic path search;
- silently replacing the graph-native query with a new SQL BFS would undermine the Stage 7 architecture boundary;
- the rest of the product remains usable through SQL, so only the advanced path feature is unavailable.

The endpoint must return a bounded, explicit capability-unavailable response rather than an internal exception or fabricated path.

---

## 4. Path search semantics

`Neo4jGraphStore.find_concept_paths(...)` returns storage-neutral `GraphPath` values.

### Bounds

- `max_depth`: 1..8, endpoint default 6;
- `limit`: 1..5, endpoint default 3;
- start Concepts: 1..10;
- supported relations: `prerequisite_of`, `related_to` only.

### Direction

`GraphEdgeRef` always records canonical SQL/Neo4j edge direction:

```text
from_node -> to_node
```

and separately records:

```text
traversed_forward = true / false
```

For `prerequisite_of`:

- outgoing requires path traversal to follow canonical `from -> to`;
- incoming requires reverse traversal;
- both permits either.

For symmetric `related_to`, either traversal orientation is valid regardless of stored canonical pair orientation.

### Cycle prevention

A returned path must be a simple node path: the same Concept may not appear twice in one path.

### Ordering

V1 orders candidate paths by:

1. fewer hops first;
2. for equal depth, higher path confidence first;
3. deterministic Concept / Edge IDs as the final tie-break.

Path confidence is the product of bounded edge confidences. It is a ranking signal, not a probability.

---

## 5. SQL overlay semantics

After Neo4j returns Concept/Edge IDs, `knowledge_path_service.py` rehydrates the product response from Canonical SQL.

### Concept node overlay

For each Concept:

- `name`;
- optional `description`;
- `mastery_estimate`;
- `confidence`;
- `forgetting_risk`;
- learner evidence counts;
- `is_start` / `is_target`;
- learning status.

V1 reuses the existing prerequisite-gap thresholds:

```text
mastered:
  mastery >= 70
  AND confidence >= 0.45

weak:
  state exists
  AND not mastered

unseen:
  no UserConceptState / no usable learner evidence projection
```

These are presentation buckets, not a new Canonical learner model.

### Edge provenance overlay

For every `ConceptEdge` in the path:

- edge type;
- edge confidence;
- edge source;
- confirmed `ConceptSourceEvidence` (bounded to 3 items per edge);
- provenance status.

Provenance status:

```text
confirmed_evidence  -> at least one confirmed ConceptSourceEvidence
confirmed_manual    -> confirmed manual edge without source excerpt
missing_evidence    -> confirmed edge exists but no confirmed source evidence
```

A path may still be returned with `missing_evidence`, but the API must say so explicitly. It must never invent an explanation.

Neo4j itself continues to store no evidence excerpt or document body.

---

## 6. API contract

Feature flag:

```text
KNOWLEDGE_PATH_ENABLED=false
```

The flag is independent from `GRAPH_BACKEND`. It gives the product feature its own rollback switch.

Endpoint:

```http
POST /api/knowledge/learning-path
```

Request:

```json
{
  "start_concept_ids": [101],
  "target_concept_id": 205,
  "max_depth": 6,
  "relation_types": ["prerequisite_of"],
  "limit": 3
}
```

Validation:

- Knowledge V2 must be enabled;
- Knowledge Path feature must be enabled;
- start/target Concepts must all be confirmed and owned by the current user;
- duplicate starts are normalized;
- relation types are allowlisted;
- no raw Cypher or relationship labels are accepted from the client.

Successful response shape:

```json
{
  "status": "ok",
  "target": {"concept_id": 205, "name": "LangGraph"},
  "paths": [
    {
      "depth": 4,
      "score": 0.72,
      "nodes": [
        {
          "concept_id": 101,
          "name": "Tool Calling",
          "learning_status": "mastered",
          "mastery_estimate": 84.0,
          "confidence": 0.82,
          "forgetting_risk": 0.12,
          "learner_evidence": {"total": 5, "direct": 4},
          "is_start": true,
          "is_target": false
        }
      ],
      "edges": [
        {
          "relation_type": "prerequisite_of",
          "confidence": 0.9,
          "provenance_status": "confirmed_evidence",
          "evidence": []
        }
      ]
    }
  ],
  "runtime": {
    "requested_backend": "neo4j",
    "effective_backend": "neo4j"
  }
}
```

No path:

```json
{
  "status": "no_path",
  "paths": []
}
```

Capability unavailable is mapped by the router to HTTP `503` with a safe, fixed error detail. Internal query text, credentials, or driver exceptions are never returned.

If the target is already one of the start Concepts, the service returns one depth-0 path containing only the target/start Concept; this does not require Neo4j traversal.

---

## 7. Explainability rule

The system must be able to answer, for every returned hop:

```text
What relation connects these Concepts?
Was the relation traversed in its canonical direction?
How confident is the relation?
What SQL evidence/provenance supports it?
If no evidence exists, does the response say that explicitly?
```

It must not answer “why” using an LLM-generated narrative that is unsupported by the returned graph path.

Natural-language explanation may be added later as a presentation layer, but structured path/provenance remains the truth.

---

## 8. Security and isolation

Every layer remains user-scoped:

- Neo4j nodes and relationships must have matching `user_id`;
- SQL rehydration must filter every Concept / Edge / Evidence / learner state by current `user_id`;
- foreign Concept IDs are rejected/not found, not partially returned;
- path results containing an unexpected or missing SQL-owned node/edge are rejected instead of partially trusted;
- source excerpts never come from Neo4j.

---

## 9. Phase 3.1 acceptance

Minimum acceptance before moving to Explainable Multi-hop Association:

- at least 10 synthetic path cases covering direct, multi-hop, multiple path, no path, cycle, direction, related_to, weak/unseen overlay, missing edge evidence, and cross-user isolation;
- real Neo4j integration verifies bounded path execution;
- 0 cross-user paths;
- shortest-first / confidence tie-break deterministic;
- every edge has confirmed provenance or explicit `missing_evidence` / `confirmed_manual`;
- stale projection / outside rollout / Neo4j failure produces capability unavailable, not stale/fabricated path;
- target-already-start depth-0 case works without graph traversal;
- existing Stage 0-7 Knowledge regression remains green.

## 10. Implementation order

```text
1. Freeze this API/product contract
2. Implement Neo4jGraphStore.find_concept_paths()
3. Implement SQL overlay service
4. Add authenticated endpoint + feature flag
5. Add synthetic contract tests
6. Run disposable real Neo4j path integration
7. Update docs / benchmark evidence
8. Create GitHub checkpoint ✅
```
