# Mnemox Stage 5 / Stage 6 Recovery Manifest

> Updated: 2026-09-04
> Branch: `backup/stage5-stage6-recovery-20260903`
> Base commit: `ac12ea5698d8b5a5370579a0e432a5ea1d37fa6e`
> Status: **recovery asset / non-merge-ready**

## Purpose

The VPS checkout at `/home/cloudcli/projects/mnemox` contains the verified Knowledge V2 Stage 0-6 development state, but also contains unrelated historical dirty/untracked work. This recovery branch deliberately does not pretend that the dirty checkout is a clean merge-ready feature branch.

Do not merge this branch into `main` as-is. Reconstruct a clean Knowledge V2 branch first, then reapply only the verified deltas recorded here.

## Final stage status

### Stage 5

Engineering complete. Real anonymous Chinese/bilingual corpus and human association-quality acceptance remain separately deferred.

Representative 5,000-Claim sparse results:

```text
SQLite reference p95   423.94 ms -> FTS5 10.58 ms   (~40.07x)
PostgreSQL reference   407.20 ms -> FTS  29.03 ms   (~14.03x)
parity                 true
```

### Stage 6

**Complete on 2026-09-04. Final decision: Neo4j NO-GO; Graphiti NO-GO. Stage 7 is not entered for these candidates.**

Product architecture remains:

```text
SQLite / PostgreSQL = canonical source
SqlGraphStore         = product graph queries
Chroma                = rebuildable dense projection
Sparse FTS            = rebuildable lexical projection
Neo4j / Graphiti      = retained Spike/reproduction code only
```

`create_graph_store()` remains SQL-only even if candidate `*_ENABLED` flags are accidentally set.

## Neo4j evidence

Passed:

- real Neo4j 5.26 + Python driver 6.3 integration;
- parameterized fixed Cypher; no Text2Cypher;
- user isolation, rebuild, source deletion, auth failure isolation;
- independent `neo4j_graph` outbox target, retry and DLQ;
- projection lag diagnostics;
- no Claim/Evidence/Unit body properties in the graph;
- 1,000/5,000 Claim ID/path/score parity with SQL = 100%; cross-user/raw-property violations = 0.

30-anchor steady-state p95:

```text
1000 direct    SQL 16.918 ms / Neo4j 19.393 ms
1000 shared    SQL 12.084 ms / Neo4j  8.905 ms
1000 combined  SQL 29.195 ms / Neo4j 25.010 ms
5000 direct    SQL 23.706 ms / Neo4j 25.766 ms
5000 shared    SQL 23.087 ms / Neo4j 16.742 ms
5000 combined  SQL 33.969 ms / Neo4j 19.199 ms
```

Neo4j has a real signal on larger shared/combined traversals, but direct queries do not show stable benefit. Disposable Stage 6 containers also showed roughly `0.7-1.0 GiB` memory and `~0.52 GiB` `/data`, while production would add a second database, backup/restore/credential/monitoring work and still require SQL for desktop mode. The mandatory net-benefit gate therefore failed.

## Graphiti evidence

Verified against real `graphiti-core 0.30.1` + Neo4j:

- telemetry forced off;
- raw episode storage off;
- legal group key is `mnemox_user_<id>`; the earlier colon form is rejected by real Graphiti search;
- confirmed/current/evidenced Claim ingestion boundary;
- reviewed temporal declarations only: confirmed/superseded/expired;
- staged/ignored/inaccurate/foreign data excluded;
- source-revision supersede invalidation;
- current/historical as-of filtering using `valid_at / invalid_at / expired_at`;
- only deterministic episode UUIDs are mapped back to canonical `MemoryDeclaration.id`;
- search failure does not expose the query or poison SQL transactions.

A real BM25-only integration used official Graphiti client base classes whose model methods raise on any call, so the benchmark proves **0 LLM / embedding / reranker calls**. Graphiti 0.30 still requires non-null vector properties for Entity/Edge saves, so deterministic local 1024-d zero vectors were used only to isolate BM25 search behavior.

Fair same-recall benchmark, 30 unique-token queries:

```text
100 facts:  SQL Recall@5 1.0, p95  8.281 ms
            Graphiti     1.0, p95 14.242 ms
1000 facts: SQL Recall@5 1.0, p95  9.616 ms
            Graphiti     1.0, p95 19.147 ms
external model calls = 0
```

Graphiti's lowest-cost search mode is slower than existing Temporal SQL at the same recall, and normal `add_episode` usage would add LLM/embedding/reranker cost while SQL must remain authoritative for fact identity, review, conflicts and validity. The mandatory net-benefit gate therefore failed.

## Final validation

```text
Stage 6 contract/unit             13 passed
real Graphiti + real Neo4j         3 passed
Stage 0-6 knowledge regression    75 passed, 4 skipped
Association V2 explicit Recall@5   1.0
Association V2 implicit Recall@5   1.0
user isolation violations          0
deleted source residual hits       0
unsupported display                0
negative false positives           0
Graphiti benchmark model calls     0
git diff --check                   passed
```

The optional skips are environment-gated external integration tests; the same run explicitly executed and passed the real Graphiti/Neo4j integrations against a disposable container. The only warning observed is an internal `graphiti-core 0.30.1` Pydantic class-config deprecation.

The disposable Stage 6 Neo4j container was removed after verification. Default Compose remains `db / backend / frontend`; Neo4j only appears under the optional `graph-shadow` profile.

## Current SHA256 inventory

```text
98968ceb1e7d3fe83603e3a3563eb461ad1b97b4a74acb23546bf617228888f1  backend/app/services/sparse_knowledge_index.py
f46dd95c7c89b86b13bc89a0e8ec27d458d9bad115e1f8d0d2f05fa826a21d81  backend/app/services/association_reranker_service.py
58505351ede956fad4eeb2b5766d8b484d349b011d8a07851205b52aed4538fd  backend/app/services/knowledge_projection_service.py
d1cf27c63c29b54d77149f93c7888e7762779b1ef8c71f1a1b05d662ab425dd2  backend/app/services/knowledge_projection_worker.py
cda1495a5a8fc6defd68d3780621561bb74636796ef2f662c7088130b31d3742  backend/app/services/association_v2_service.py
43534f2d8a2d97970f0005ea23371669aacdd15e99ba1f154cfb1facd6c71eb2  backend/app/services/graph_store/neo4j_store.py
d4f3dd335bfc7dbdfc054400804649146d6e95de968f1de2b951f3de988c4472  backend/app/services/graph_shadow_service.py
0ffd4934223b0dcd2ce2333ce050f6f7361a62a9606b610662dd7e25762f895a  backend/app/services/graphiti_shadow_service.py
19d7459d8270ac3faab2a5483db25c543fbbafac09a5f1b34464bed19ca5e005  backend/evaluate_sparse_knowledge.py
b17d2e32c3ab368f20b5042569ed8bbb465c07bdb2831cd594e49ed5414eeeef  backend/evaluate_graph_shadow.py
b61c0f7ee3507a3f2b98f490f10ceae7c8e5a0b2d7398c3c764c02c8538514ed  backend/evaluate_graphiti_shadow.py
519a544eb21150c871f3c72d16c7da814145f64ce9cc67aa5bc7fac1dc1ce583  backend/tests/test_graph_shadow_stage6.py
68df777383f2056ea27be5a5675804c36628a3c3f083a06d1716c39b12b4496a  backend/tests/test_graphiti_shadow_integration.py
56e4b0900f780e668be4731e3cc3d51b3f41a59cd7aedcc04d7d8a683b9b85e1  backend/tests/test_neo4j_shadow_integration.py
4a1a3decbba55ba313f4da4f4570578002b3c1a9c66649c8ebb03b65a8307289  docs/superpowers/specs/2026-09-04-mnemox-v2-stage6-final-go-no-go.md
797257581868d6461e11693372a8499b82e60e02d90830ac8ef8c85edf434227  docs/updates/2026/2026-09-04_mnemox-v2-stage6-final.md
```

## Clean reconstruction guidance

Do not blindly copy shared dirty checkout files. Start from a clean branch containing the complete Stage 0-4 Knowledge V2 closure, reapply Stage 5 verified deltas, run Stage 0-5 tests/benchmarks, then reapply the Stage 6 Spike/evaluator files only if historical reproducibility is needed.

For product development after this point, do **not** continue to Stage 7 for Neo4j/Graphiti. The next useful work is Stage 4/5 real anonymous/human quality acceptance, product gray rollout, or a clean Git-history reconstruction.
