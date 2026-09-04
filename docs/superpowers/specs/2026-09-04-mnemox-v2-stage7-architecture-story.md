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

### Pain point at the beginning

The system needed to answer:

- Which source/revision does a fact come from?
- Is the Claim reviewed?
- Is its Evidence still valid?
- Was the source deleted or superseded?
- Can the user correct/merge/reject it?
- Can SQLite desktop and PostgreSQL server use the same domain rules?
- Can a transaction atomically update business truth?

These are mostly **data ownership and lifecycle** problems, not graph traversal problems.

### Why SQL fit

SQL gave Mnemox:

- explicit transactions;
- foreign keys and uniqueness constraints;
- auditable review/lifecycle columns;
- straightforward user isolation;
- mature migrations;
- SQLite/PostgreSQL compatibility;
- cheap backup/recovery;
- a natural canonical store for Evidence and source text.

A graph database could represent relationships earlier, but it would not remove the need for the canonical lifecycle model. Starting with it would have created two difficult problems at once: product semantics **and** cross-store consistency.

---

## 4. Why introduce GraphStore before Neo4j

Once Claim/Concept/Relation became real domain objects, the product started asking graph-shaped questions.

The wrong move would have been:

```text
Router / business service
    -> Neo4j-specific query / node / relationship types everywhere
```

That would couple the product to one storage engine before its value was proven.

So Stage 4 introduced `GraphStore` first.

The abstraction owns business-level operations such as:

```text
expand claims
source claims
find concept paths
```

rather than exposing Cypher.

This made three later decisions possible:

1. keep `SqlGraphStore` as the safe default;
2. benchmark Neo4j without rewriting product APIs;
3. make graph-native capabilities explicitly unsupported in SQL instead of secretly building a second generic graph engine in relational code.

The important lesson is:

> Abstract the business capability first; choose/swap the execution engine behind it only when the workload proves the need.

---

## 5. Why Stage 6 said NO-GO

Stage 6 was a Shadow experiment, not a migration project.

### Neo4j evidence

At 5,000 Claims:

```text
combined SQL p95     ~33.97 ms
combined Neo4j p95   ~19.20 ms
speedup               ~1.77x
```

But direct/simple paths did not show a stable advantage, while the candidate added roughly:

```text
memory    ~0.7–1.0 GiB
disk      ~0.52 GiB in the test environment
```

plus another service, credentials, backup, rebuild and failure modes.

The conclusion was not “Neo4j is bad.” It was:

> Replacing the existing runtime for the existing queries did not clear the ROI threshold.

### Graphiti evidence

Stage 6 Graphiti BM25 temporal comparison achieved the same Recall@5 as SQL (`1.0`) in the bounded test, but its p95 was slower and normal Graphiti ingestion can introduce model/embedding cost.

Again, correctness was not the blocker. Product/runtime value was.

This is why the Stage 6 decision remains valid even after Stage 7.

---

## 6. Why Stage 7 reopened Neo4j

The goal changed.

Mnemox now needed not only a shippable product baseline, but also:

- a real graph database backend;
- graph-native feature design;
- projection/readiness/fallback engineering;
- a credible technology-selection story for job interviews.

That made a limited optional backend worthwhile.

Stage 7 therefore chose:

```text
GRAPH_BACKEND=sql       # default
GRAPH_BACKEND=neo4j     # optional server execution backend
```

and kept the following invariants:

- SQL is Canonical;
- Neo4j is rebuildable;
- user rollout is deterministic;
- projection must be initialized/caught up before primary reads;
- normal read queries can fall back to SQL when semantics match;
- graph-native capability does not get a fake SQL fallback;
- credentials missing -> fail closed;
- desktop does not require Neo4j.

---

## 7. The first feature that actually justifies Neo4j: Knowledge Path

Simply translating an existing SQL Association query into Cypher would not prove graph value.

Knowledge/Learning Path asks a different question:

```text
I know A.
I want to reach D.
What prerequisite path connects them?
Which nodes on that path are weak/unseen for me?
Why does each edge exist?
```

Example:

```text
Tool Calling
  -> Agent Runtime
  -> State Management
  -> Workflow
  -> LangGraph
```

Neo4j solves only the topology problem:

```text
bounded path traversal
```

Then SQL rehydrates:

- Concept identity;
- learner mastery/confidence;
- LearnerEvidence;
- ConceptEdge provenance;
- source evidence.

This separation is deliberate:

> The graph engine discovers the route; Canonical SQL decides what the route means and whether it may be shown.

A generic SQL BFS was intentionally not implemented just to claim backend parity. If the advanced graph backend is unavailable, the advanced path capability is unavailable while the rest of the product keeps working.

---

## 8. Explainable Multi-hop without leaking storage internals

Association V2 already had internal graph-hit paths, but internal paths are not automatically good product explanations.

Stage 7 added explanation as a post-ranking enrichment:

```text
rank candidates first
    -> optional graph explanation
    -> Canonical SQL validation
    -> presentation-safe explanation
```

Consequences:

- enabling explanation does not change ranking order/scores;
- missing Neo4j/path does not delete an otherwise valid Association result;
- the explanation surface does not expose SQL IDs, Neo4j IDs or Cypher;
- no valid path -> no fabricated explanation;
- every visible hop comes from validated relation/provenance.

This is an example of keeping **retrieval/ranking truth** separate from **presentation explainability**.

---

## 9. Why Graphiti is separate from Neo4jGraphStore

Neo4jGraphStore and Graphiti solve different problems.

| Layer | Main job |
| --- | --- |
| Neo4jGraphStore | execute graph topology over Claim/Concept relations |
| Graphiti Temporal Slice | experiment with temporal/episodic fact evolution |
| MemoryDeclaration SQL | authoritative temporal fact lifecycle |

Graphiti was not made another GraphStore backend because it would mix two distinct semantics:

```text
knowledge graph traversal
vs
fact history / valid-time / episodic evolution
```

Stage 7 V1 only projects reviewed `MemoryDeclaration` rows and supports:

- current lookup;
- historical `as_of` lookup;
- supersede/invalidation;
- user isolation;
- delete/rebuild.

It does not ingest all chat history and it cannot approve facts.

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

Both cases:

```text
cross-user leakage       0
external LLM calls       0
external embedding calls 0
configured model cost    0
```

This is a valuable negative/limited result:

> For current reviewed temporal declarations, relational valid-time queries are simpler and substantially faster. Graphiti should remain Experimental until a genuinely episodic/multi-fact temporal use case shows enough product value.

Choosing **not** to make a technology mandatory after implementing it is part of the engineering result.

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

Deployment property verified in Docker Compose:

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

This lets open-source/local users keep a lightweight product while server users can explicitly opt into graph functionality.

---

## 12. What I would say in an interview

A concise version:

> I initially kept PostgreSQL/SQLite as the canonical knowledge store because the hard problems were transactions, evidence, review state and lifecycle rather than graph traversal. As the domain became graph-shaped, I introduced a storage-neutral GraphStore and evaluated Neo4j in Shadow instead of migrating blindly. The benchmark showed Neo4j was correct and faster for some combined graph workloads, but not enough to justify making it a mandatory runtime, so Stage 6 was NO-GO for default traffic. Later, because the product also needed graph-native features and I wanted a production-like portfolio implementation, I added Neo4j as an optional rebuildable backend with projection readiness, deterministic rollout and SQL fallback. I then used it for a real bounded Knowledge Path feature rather than translating ordinary SQL to Cypher. I also evaluated Graphiti separately for temporal memory; it was correct but much slower than SQL in the tested workload, so I kept SQL temporal truth and left Graphiti experimental. The main lesson was to let workload evidence determine where specialized infrastructure belongs.

Follow-up questions this story can answer:

1. Why not Neo4j from day one?
2. Why abstract GraphStore before choosing a graph DB?
3. How do you maintain consistency between SQL and Neo4j?
4. What happens when Neo4j is stale/down?
5. Why is Knowledge Path graph-native?
6. Why did you deliberately avoid generic BFS in SQL?
7. Why is Graphiti not a replacement for MemoryDeclaration?
8. How did benchmark evidence change the architecture?
9. How do desktop/local and server deployments differ?
10. How would you evolve this after real-user data?

---

## 13. What remains after Stage 7 engineering close

The next evidence should come from **dogfooding**, not more synthetic architecture work.

The user will import their own real Chinese/English technical notes through a cloud WebUI and evaluate:

- Claim extraction quality;
- Concept/relation quality;
- Association false/forced relevance;
- Knowledge Path usefulness;
- explanation usefulness;
- temporal memory usefulness;
- latency and fallback behavior on real data.

That work is intentionally separated from Stage 7 implementation so that synthetic engineering acceptance is not mislabeled as real-user product validation.
