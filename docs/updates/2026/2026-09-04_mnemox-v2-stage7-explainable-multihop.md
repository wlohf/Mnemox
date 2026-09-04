# Mnemox V2 Stage 7 — Explainable Multi-hop Association V1

> Date: 2026-09-04
> Status: Phase 3.2 complete
> Default: `ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED=false`

## What changed

Association V2 can now optionally attach a presentation-safe structured explanation showing why a candidate is related.

Example shape:

```text
Current content
  -> Tool Calling
  -> prerequisite_of
  -> Agent Runtime
  -> Related knowledge
```

The explanation layer runs after ranking. It does not alter Association candidate scores or ordering.

## Architecture

```text
Association V2 ranking
  -> displayed candidate
  -> optional explanation enrichment
  -> GraphStore bounded Concept path
  -> Canonical SQL rehydrate
  -> presentation-safe explanation
```

Neo4j may discover topology only. SQL remains Canonical for Concept identity, ConceptEdge truth and provenance.

## Safety rules

The new `explanation` object does not expose:

- Claim SQL IDs;
- Concept SQL IDs;
- ConceptEdge IDs;
- Neo4j keys;
- Cypher text.

Legacy Association compatibility fields are unchanged in this phase.

Any graph/runtime failure, stale projection, outside-rollout routing, SQL rehydrate mismatch or missing valid path simply removes the optional explanation. The underlying Association result remains available.

No LLM narrative is generated. `summary` uses deterministic templates backed by the verified structured path.

## Provenance

Each relation step explicitly reports one of:

```text
confirmed_evidence
confirmed_manual
missing_evidence
```

Evidence excerpts are loaded only from Canonical SQL and are bounded.

## Feature flag

```text
ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED=false
```

This is independent from `ASSOCIATION_V2_ENABLED` so the explanation surface can be rolled back without disabling Association V2 itself.

## Tests

Focused Association/explanation tests:

```text
16 passed
```

Covered:

- shared-Concept explanation without graph traversal;
- multi-hop Concept path rendering;
- prerequisite direction;
- `related_to` symmetry;
- evidence/manual/missing provenance;
- foreign/mismatched graph path rejection;
- graph failure isolation;
- no internal DB IDs in the new explanation surface;
- feature flag off => no explanation call;
- feature flag on => explanation only enriches output;
- ranking order and score unchanged by explanation flag.

Stage 0-7 Knowledge wide regression with real Neo4j integration included:

```text
127 passed, 1 warning
```

The only warning remains the existing third-party `graphiti_core` Pydantic v2 class-based config deprecation.

## Next block

Phase 3 graph-native product capability is now complete at V1 scope.

Next work should move to:

```text
real-data benchmark / long-running rollout observation
-> Graphiti Temporal/Episodic Vertical Slice
```

Optional graph analytics should only be added if one algorithm has a clear product surface; it is not required merely to showcase graph terminology.
