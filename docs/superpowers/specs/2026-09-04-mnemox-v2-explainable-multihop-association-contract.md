# Mnemox V2 Stage 7 — Explainable Multi-hop Association Contract

> Date: 2026-09-04
> Status: Phase 3.2 implementation contract
> Depends on: Association V2 + Optional Neo4j Runtime + Knowledge/Learning Path V1

## 1. Why this feature exists

Association V2 can already rank related Claims, but a ranked result is not the same as an explanation.

The product question is:

```text
Why is this item related to what I am reading / asking?
```

Phase 3.2 adds a structured, auditable explanation path such as:

```text
Current Claim
  -> Tool Calling
  -> prerequisite_of
  -> Agent Runtime
  -> Related Claim
```

The explanation is not an LLM narrative. It is a presentation-safe rendering of a graph path that can be revalidated against Canonical SQL.

## 2. Product boundary

V1 supports explanations when Association has at least one confirmed anchor Concept and the related Claim has at least one confirmed Concept link.

The graph-native middle section may use:

- `prerequisite_of`;
- `related_to`.

Traversal is bounded and may use either direction because Association asks "how are these connected?", not "what must I learn first?".

V1 does not:

- use Text2Cypher;
- invent missing ConceptEdges;
- infer a path from free text when no confirmed anchor Concept exists;
- expose raw Neo4j/Cypher output;
- replace the existing Association ranker;
- turn SQL into a generic BFS engine.

## 3. Runtime / fallback policy

Multi-hop explanation is optional enrichment.

```text
Association ranking
  -> existing SQL / dense / sparse / graph fallback behavior

Multi-hop explanation
  -> attempt only when graph-native execution is ready
  -> if unavailable / stale / outside rollout / no valid path: omit explanation
```

Explanation failure must never remove an otherwise valid Association result.

This is different from Knowledge Path, where the path itself is the requested product capability.

## 4. Canonical trust boundary

Neo4j may return only topology IDs and traversal direction.

Before an explanation is returned, SQL must rehydrate and verify:

- anchor/related Claim ownership and visibility;
- confirmed ClaimConceptLink ownership;
- confirmed Concept identity;
- confirmed ConceptEdge identity/type/direction;
- optional ConceptSourceEvidence provenance;
- active/current knowledge source lifecycle where Claim visibility requires it.

If any path element cannot be rehydrated consistently, the explanation is discarded.

## 5. Presentation-safe response

Association keeps its existing compatibility fields. A new optional field is added:

```json
{
  "explanation": {
    "kind": "graph_path",
    "summary": "Tool Calling 通过 prerequisite_of 连接到 Agent Runtime",
    "steps": [
      {"type": "anchor", "label": "当前内容"},
      {"type": "concept", "name": "Tool Calling"},
      {
        "type": "relation",
        "relation_type": "prerequisite_of",
        "directed": true,
        "traversed_forward": true,
        "provenance_status": "confirmed_evidence"
      },
      {"type": "concept", "name": "Agent Runtime"},
      {"type": "related_claim", "label": "候选知识"}
    ],
    "evidence": [
      {
        "source_type": "material",
        "source_id": 123,
        "source_version": 2,
        "excerpt": "..."
      }
    ]
  }
}
```

### Internal ID rule

The new `explanation` object must not expose:

- Concept SQL IDs;
- Claim SQL IDs;
- ConceptEdge IDs;
- Neo4j node keys;
- Cypher query text.

The existing Association compatibility payload may continue to contain legacy IDs until a separate API-version cleanup; Phase 3.2 must not copy those IDs into the new explanation surface.

## 6. Explanation construction

For each displayed Association candidate:

1. obtain confirmed anchor Concept IDs from the query/source representation;
2. obtain confirmed Concept links for the related Claim;
3. ask GraphStore for bounded Concept paths between anchor Concepts and related Concepts;
4. choose the best valid path by:
   - fewer hops;
   - higher canonical SQL confidence;
   - deterministic names/IDs internally as tie-break only;
5. SQL-rehydrate Concepts/Edges/Evidence;
6. render a presentation-safe explanation.

If anchor and related Claim share the same Concept, V1 may return a zero-Concept-edge explanation:

```text
Current Claim -> Shared Concept -> Related Claim
```

This case does not require a Neo4j traversal.

## 7. Summary text rule

`summary` is deterministic template text, not model-generated prose.

Examples:

```text
共同关联到「Tool Calling」

「Tool Calling」通过 prerequisite_of 连接到「Agent Runtime」

「A」通过 prerequisite_of → related_to 连接到「C」
```

For paths longer than two graph edges, the summary may collapse middle relations, but `steps` remains the complete structured truth.

No explanation is returned if the system cannot construct a truthful deterministic summary from the verified path.

## 8. Provenance

Each graph relation step exposes one of:

```text
confirmed_evidence
confirmed_manual
missing_evidence
```

Evidence excerpts come only from Canonical SQL and are bounded.

`missing_evidence` is allowed for an already-confirmed edge but must be explicit.

## 9. Feature flag

Add an independent default-off flag:

```text
ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED=false
```

Why separate it from `ASSOCIATION_V2_ENABLED`:

- Association ranking is already a product capability;
- multi-hop explanation adds optional graph dependency and response shape;
- it needs an independent rollback switch during rollout.

## 10. Acceptance

Before Phase 3.2 is complete:

- shared-Concept zero-edge explanation works;
- one-hop and multi-hop Concept paths work;
- prerequisite direction and related_to symmetry are preserved;
- every graph edge is SQL-rehydrated;
- edge provenance is evidence/manual/missing explicitly;
- no internal DB IDs appear inside the new `explanation` object;
- 0 cross-user explanation paths;
- stale/outside-rollout/Neo4j failure only removes explanation, not Association result;
- no valid path => no fabricated explanation;
- existing Association ranking/order stays unchanged when explanation flag is off;
- Stage 0-7 Knowledge regression remains green.

## 11. Implementation order

```text
1. Freeze this contract
2. Add explanation service with SQL rehydration
3. Integrate as optional post-ranking enrichment
4. Add contract + failure-isolation tests
5. Run real Neo4j integration
6. Update docs / checkpoint
```
