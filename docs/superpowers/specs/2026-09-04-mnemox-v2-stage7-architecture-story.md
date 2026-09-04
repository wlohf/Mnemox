# Mnemox V2 Stage 7 — Architecture Story

> Date: 2026-09-04  
> Purpose: architecture review + interview/learning narrative  
> Status: verified engineering story; real-note human evaluation follows in WebUI dogfooding

## 1. The short version

Mnemox did **not** start with Neo4j or Graphiti because the first problem was not “how to traverse a graph.” The first problem was “how to keep reviewed knowledge, evidence, lifecycle, transactions and desktop/server behavior correct.” SQL was the simpler and stronger source of truth for that job.

As the product became more graph-shaped, Mnemox introduced a storage-neutral `GraphStore` boundary. Stage 6 then used real Neo4j and Graphiti as Shadow candidates and deliberately returned **default Runtime NO-GO**: both were correct enough, but neither justified becoming a mandatory runtime dependency for the existing workload.

Stage 7 did not reverse that decision. It changed the project objective from only product ROI to:

```text
product value
+ architecture depth
+ reusable technical capability
+ job/portfolio evidence
```

Therefore Neo4j became an **optional execution backend**, not a new source of truth. It was given genuinely graph-native work — Knowledge/Learning Path and explainable multi-hop traversal — while SQL remained Canonical. Graphiti was given a separate Temporal/Episodic slice and again measured against SQL rather than promoted by default.

The final result is intentionally asymmetric:

```text
SQL / PostgreSQL / SQLite
  = mandatory Canonical truth

Chroma / Sparse / Neo4j / Graphiti
  = rebuildable or optional projections/execution layers
```

That asymmetry is the main architectural decision of Stage 7.

---

## 2. Evolution diagram

```text
Chunk RAG
  |
  v
Canonical Source / Revision / Unit
  |
  v
Claim + Evidence
  |
  v
Concept + Relation
  |
  +------------------------------+
  |                              |
  v                              v
Dense / Sparse Retrieval     SqlGraphStore
                                 |
                                 v
                           GraphStore Protocol
                                 |
                      +----------+----------+
                      |                     |
                      v                     v
                 SQL Backend        Optional Neo4j Backend
                      |                     |
                      |              Knowledge/Learning Path
                      |              Explainable Multi-hop
                      |                     |
                      +----------+----------+
                                 |
                                 v
                      Canonical SQL Rehydrate

MemoryDeclaration (SQL Temporal Truth)
                 |
                 +--------------------------+
                                            |
                                            v
                               Experimental Graphiti
                               Temporal/Episodic Slice
```

The arrows from Canonical SQL toward projections are one-way architectural ownership arrows. A projection may accelerate/discover a result, but it does not become the authority merely because it is specialized.

---

## 3. Why SQL came first

The early system had to solve source/revision identity, reviewable Claims, Evidence, deletion/supersede lifecycle, user correction and SQLite/PostgreSQL transactional behavior. These are data ownership/lifecycle problems before they are graph traversal problems.

SQL therefore provided the canonical base through explicit transactions, constraints, migrations, ownership filters, auditable state and desktop/server compatibility. Starting with a graph database would not remove these requirements; it would add cross-store consistency before product semantics were stable.

---

## 4. Why introduce GraphStore before Neo4j

Once Claim/Concept/Relation became real domain objects, the product started asking graph-shaped questions. Instead of coupling routers and business services to Cypher and Neo4j types, Mnemox introduced a business-level `GraphStore` contract first.

This allowed:

1. `SqlGraphStore` to remain the safe default;
2. Neo4j to be benchmarked without changing product APIs;
3. graph-native capabilities to be explicitly unsupported in SQL instead of creating a hidden generic relational graph engine.

The principle is:

> Abstract the business capability first; select the execution engine only when the workload proves the need.

---

## 5. Why Stage 6 said NO-GO

Stage 6 was a Shadow experiment, not a migration project.

At 5,000 Claims Neo4j combined p95 improved from about `33.97 ms` to `19.20 ms`, but direct/simple paths showed no stable advantage while the test service added roughly `0.7–1.0 GiB` memory, about `0.52 GiB` disk and another operational surface.

Graphiti Stage 6 reproduced the bounded SQL temporal retrieval correctly but was slower in that test, while its normal ingestion path can introduce model/embedding cost.

Therefore Stage 6 concluded that neither candidate should become a mandatory default runtime. The conclusion was about **ROI for the current workload**, not correctness or technology quality.

---

## 6. Why Stage 7 reopened Neo4j

The project objective expanded from pure product ROI to product value + architecture depth + reusable technical capability + job/portfolio evidence.

Stage 7 therefore introduced:

```text
GRAPH_BACKEND=sql       # default
GRAPH_BACKEND=neo4j     # optional server execution backend
```

while preserving:

- SQL Canonical truth;
- rebuildable Neo4j projection;
- deterministic rollout;
- projection readiness before Neo4j reads;
- SQL fallback for compatible read semantics;
- explicit capability-unavailable behavior for graph-native paths;
- fail-closed credentials;
- no mandatory Neo4j dependency for desktop/default deployment.

This does not contradict Stage 6 because Stage 6 answered “should we switch the default runtime?” while Stage 7 answered “is it worth building a real optional graph backend for graph-native features and technical depth?”

---

## 7. Knowledge Path is the first feature that actually justifies Neo4j

Knowledge/Learning Path asks:

```text
I know A.
I want to reach D.
What prerequisite path connects them?
Which nodes are weak/unseen for me?
Why does each edge exist?
```

Neo4j solves only bounded topology traversal. SQL then rehydrates Concept identity, learner mastery/confidence, LearnerEvidence, ConceptEdge provenance and source evidence.

The graph engine discovers the route; Canonical SQL decides what the route means and whether it may be shown.

A generic SQL BFS was intentionally not built merely to preserve parity.

---

## 8. Explainable Multi-hop stays separate from ranking

Stage 7 added explanation after candidate ranking:

```text
rank candidates
  -> optional graph explanation
  -> Canonical SQL validation
  -> presentation-safe explanation
```

Therefore enabling explanation does not change ranking scores/order, graph failures do not remove otherwise valid Association results, internal SQL/Neo4j IDs and Cypher are not exposed, and no valid path means no fabricated explanation.

---

## 9. Why Graphiti is separate from Neo4jGraphStore

| Layer | Main job |
| --- | --- |
| Neo4jGraphStore | graph topology over Claim/Concept relations |
| Graphiti Temporal Slice | temporal/episodic fact evolution experiment |
| MemoryDeclaration SQL | authoritative temporal fact lifecycle |

Graphiti V1 only projects reviewed `MemoryDeclaration` rows. It supports current/as-of lookup, supersede/invalidation, user isolation and delete/rebuild, but it does not ingest all chat history and cannot approve facts.

---

## 10. Graphiti result: useful experiment, not default runtime

Stage 7 model-free benchmark:

### 60 temporal declarations

```text
SQL correctness        1.0
Graphiti correctness   1.0
SQL p95                4.766 ms
Graphiti p95           192.204 ms
Graphiti rebuild       2305.701 ms
```

### 300 temporal declarations

```text
SQL correctness        1.0
Graphiti correctness   1.0
SQL p95                2.921 ms
Graphiti p95           138.552 ms
Graphiti rebuild       9302.495 ms
```

Both cases have zero cross-user leakage and zero external LLM/embedding calls in this bounded slice.

For the current reviewed temporal declaration use case, relational valid-time queries are simpler and substantially faster. Graphiti remains Experimental until a genuinely episodic/multi-fact temporal use case demonstrates enough product value.

Choosing not to make a technology mandatory after implementing it is part of the engineering result.

---

## 11. Final Stage 7 runtime topology

```text
Default deployment
------------------
PostgreSQL / SQLite
Chroma
Sparse
SqlGraphStore
MemoryDeclaration SQL

Optional graph server profile
-----------------------------
Neo4j
Neo4jGraphStore
Knowledge/Learning Path
Explainable Multi-hop discovery

Experimental
------------
Graphiti Temporal Slice
```

Verified Docker Compose boundary:

```text
default services:
  db
  backend
  frontend

graph profile:
  db
  backend
  frontend
  neo4j
```

---

## 12. Interview version

> I initially kept PostgreSQL/SQLite as the canonical knowledge store because the hard problems were transactions, evidence, review state and lifecycle rather than graph traversal. As the domain became graph-shaped, I introduced a storage-neutral GraphStore and evaluated Neo4j in Shadow instead of migrating blindly. The benchmark showed Neo4j was correct and faster for some combined graph workloads, but not enough to justify making it a mandatory runtime, so Stage 6 was NO-GO for default traffic. Later, because the product also needed graph-native features and I wanted a production-like portfolio implementation, I added Neo4j as an optional rebuildable backend with projection readiness, deterministic rollout and SQL fallback. I then used it for a real bounded Knowledge Path feature rather than translating ordinary SQL to Cypher. I also evaluated Graphiti separately for temporal memory; it was correct but much slower than SQL in the tested workload, so I kept SQL temporal truth and left Graphiti experimental. The main lesson was to let workload evidence determine where specialized infrastructure belongs.

Useful follow-up questions:

1. Why not Neo4j from day one?
2. Why abstract GraphStore before choosing a graph DB?
3. How do you maintain consistency between SQL and Neo4j?
4. What happens when Neo4j is stale/down?
5. Why is Knowledge Path graph-native?
6. Why avoid generic BFS in SQL?
7. Why is Graphiti not a replacement for MemoryDeclaration?
8. How did benchmark evidence change the architecture?
9. How do desktop/local and server deployments differ?
10. How would you evolve this after real-user data?

---

## 13. What remains after Stage 7 engineering close

The next evidence should come from dogfooding rather than more synthetic architecture work.

The user will import real Chinese/English technical notes through a cloud WebUI and evaluate Claim extraction, Concept/relation quality, Association usefulness, Knowledge Path usefulness, explanation quality, temporal behavior and real latency/fallback observations.

That work is intentionally separated from Stage 7 implementation so synthetic engineering acceptance is not mislabeled as real-user product validation.
