# Mnemox V2 Stage 7 — Knowledge / Learning Path V1

> Date: 2026-09-04
> Status: Phase 3.1 complete
> Default runtime: SQL remains default; Neo4j remains optional

## What this block completed

Stage 7 now contains its first real graph-native product capability instead of only rewriting existing SQL queries in Cypher.

Knowledge / Learning Path accepts explicit start Concepts and one target Concept, performs bounded Neo4j path traversal, and then rehydrates the product response from Canonical SQL.

Architecture:

```text
Canonical SQL
  -> Concept / ConceptEdge / learner state / evidence truth
  -> rebuildable Neo4j graph projection
  -> bounded path traversal
  -> GraphPath IDs + direction
  -> Canonical SQL rehydrate
  -> mastery / evidence / provenance overlay
  -> authenticated Learning Path response
```

Neo4j is responsible only for topology search. It is not a second source of truth.

## Product contract

Endpoint:

```text
POST /api/knowledge/learning-path
```

Feature flag:

```text
KNOWLEDGE_PATH_ENABLED=false
```

Default semantics:

```text
relation_types = ["prerequisite_of"]
direction = outgoing
max_depth = 6
limit = 3
```

`A prerequisite_of B` means `A -> B`, so Learning Path follows prerequisite to dependent by default.

`related_to` remains explicitly opt-in and symmetric.

## Runtime behavior

Basic graph reads can fall back Neo4j -> SQL.

Knowledge Path deliberately does not invent a generic SQL BFS fallback. If Neo4j is unavailable, the user is outside rollout, the projection is stale/uninitialized, or graph-native path execution is unavailable, only this advanced capability returns a safe capability-unavailable response; the rest of the product remains available through SQL.

This preserves the architecture boundary:

```text
SQL = Canonical business truth
Neo4j = optional graph-native execution engine
```

## Explainability

Every returned path is revalidated against SQL before leaving the service.

Nodes include:

- Concept identity/name/description;
- learner mastery/confidence/forgetting risk/reliability;
- learner evidence counts;
- mastered / weak / unseen presentation status;
- start/target flags.

Edges include:

- canonical relation type/direction;
- traversal orientation;
- confidence;
- source;
- bounded confirmed ConceptSourceEvidence;
- explicit provenance status: `confirmed_evidence`, `confirmed_manual`, or `missing_evidence`.

No LLM narrative is allowed to invent a reason that is not present in the structured path/provenance.

## Safety / correctness gates

The implementation rejects instead of partially trusting path results when:

- a graph node cannot be rehydrated as a current-user confirmed Concept;
- a graph edge cannot be rehydrated as a current-user confirmed ConceptEdge;
- relation type differs between graph projection and Canonical SQL;
- a directed prerequisite edge is traversed backwards in an outgoing Learning Path;
- the path contains a cycle or malformed node/edge count;
- a returned relation type was not explicitly allowed.

Neo4j continues to store no source excerpt or learner evidence body.

## Verification

Targeted Knowledge Path / rollout / readiness suite:

```text
31 passed, 2 skipped
```

The two skips were only because the test process initially lacked the dedicated `MNEMOX_TEST_NEO4J_*` environment variables.

The already-running local disposable `neo4j:5.26-community` container was then reused and the real integration gate was executed explicitly:

```text
2 passed
```

Finally, the Stage 0-7 Knowledge regression was rerun with Knowledge Path and real Neo4j integration included:

```text
122 passed, 1 warning
```

No tests were skipped in that wide run. The only warning remains the third-party `graphiti_core` Pydantic v2 class-based config deprecation.

## What remains

Phase 3.1 is complete. The next independent block is:

```text
Phase 3.2 Explainable Multi-hop Association
```

The goal is to let Association answer not only "what is related" but "why is it related", using structured paths such as:

```text
Claim -> Concept -> prerequisite -> Concept -> Claim
```

with no fabricated explanation and no leakage of internal database IDs.
