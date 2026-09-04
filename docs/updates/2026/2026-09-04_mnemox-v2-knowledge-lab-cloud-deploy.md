# 2026-09-04 — Mnemox Knowledge Lab Cloud Dogfooding Deployment

## Status

The post-Stage-7 Knowledge Lab is deployed to the existing public Mnemox server and is ready for owner dogfooding at:

```text
https://mnemox.wlohf.com/knowledge-lab
```

The route remains authenticated. The current PostgreSQL database was empty before the deployment, so the owner can start with a fresh account and import real notes from zero.

---

## Deployment topology

```text
Browser
  -> Caddy HTTPS
  -> mnemox-frontend (Nginx)
  -> mnemox-backend (FastAPI)
  -> PostgreSQL 16
  -> Chroma / Sparse
  -> optional Neo4j 5.26
```

Public compose layers used for dogfooding:

```text
docker-compose.yml
+ docker-compose.public.yml
+ docker-compose.dogfood.yml
+ --profile graph
```

`docker-compose.dogfood.yml` is explicit and credential-free. It enables the experimental product surface only when deliberately included.

---

## Dogfooding feature state

The deployed backend has:

```text
KNOWLEDGE_V2_ENABLED=true
KNOWLEDGE_LLM_EXTRACTION_ENABLED=true
KNOWLEDGE_EMBEDDING_ENABLED=false
ASSOCIATION_V2_ENABLED=true
KNOWLEDGE_PATH_ENABLED=true
ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED=true
GRAPH_BACKEND=neo4j
NEO4J_GRAPH_ROLLOUT_PERCENT=100
GRAPHITI_ENABLED=false
```

Why this combination:

- real-note Claim extraction should exercise the LLM extraction path;
- Dense embedding remains disabled initially to reduce one external dependency while evaluating Claim/Concept/graph quality;
- Neo4j is enabled for the owner cohort so Knowledge Path can be exercised;
- Graphiti remains off because ordinary note dogfooding is testing the knowledge graph, not temporal memory.

Enabling LLM extraction does not itself call a model. A model call occurs only when the authenticated user explicitly starts extraction, using that user's configured `material_analyze` provider and the existing extraction budgets.

---

## Runtime packaging hardening found during deployment

The development venv already contained the Neo4j spike dependencies, but the production backend Dockerfile installs only `backend/requirements.txt`.

Before this deployment, `requirements.txt` did not contain the Neo4j Python driver. That meant a container could be configured with `GRAPH_BACKEND=neo4j` but fail only when the graph backend was first used.

Fix:

```text
neo4j>=6.3,<7
```

is now a formal backend runtime dependency for the Optional Neo4j Graph Backend.

Graphiti remains an experimental/spike dependency and is not promoted into the default backend image in this deployment.

The rebuilt backend image was explicitly checked:

```text
neo4j 6.3.0
Neo4jGraphStore import = ok
```

The backend container also successfully performed real Neo4j connectivity verification after deployment.

---

## Compose flag plumbing hardening

`docker-compose.yml` now passes through:

```text
KNOWLEDGE_LLM_EXTRACTION_ENABLED
KNOWLEDGE_EMBEDDING_ENABLED
```

in addition to the Stage 7 Knowledge/Graph feature flags.

The explicit owner-only overlay is:

```text
docker-compose.dogfood.yml
```

Reproducible command:

```text
docker compose \
  -f docker-compose.yml \
  -f docker-compose.public.yml \
  -f docker-compose.dogfood.yml \
  --profile graph up -d
```

---

## Database upgrade / rollback safety

Before recreating the application containers:

- existing DB migration: `20260826_14`;
- stable data counts: `users=0`, `materials=0`, `concepts=0`;
- a PostgreSQL custom-format dump was created inside the DB container:

```text
/tmp/mnemox-pre-knowledge-lab-20260904.dump
```

Size at creation: approximately `221 KiB`.

New backend startup upgraded PostgreSQL transactionally through:

```text
20260827_15
20260830_16
20260901_17
20260901_18
20260902_19
20260903_20
20260903_21
20260903_22
```

Final migration head:

```text
20260903_22
```

Backend health after migration:

```text
{"status":"ok"}
```

---

## Public reverse-proxy lesson

The first application-container recreate used only the base Compose file. The containers themselves were healthy, but this temporarily removed the frontend from the external `web` network and reset the backend public CORS/trusted-proxy override, producing public HTTP `502`.

No database or user data was affected.

The deployment was immediately reconciled with:

```text
docker-compose.yml
+ docker-compose.public.yml
+ graph profile
```

and then made reproducible with the dogfooding overlay.

Verified final frontend networks:

```text
mnemox_default
web
```

Verified backend public proxy settings:

```text
CORS_ORIGINS=["https://mnemox.wlohf.com"]
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_HOPS=2
```

---

## Public smoke evidence

Public HTTPS probes after final reconcile:

```text
https://mnemox.wlohf.com/               -> 200
https://mnemox.wlohf.com/knowledge-lab  -> 200
TLS verification result                 -> 0 (success)
```

Unauthenticated protected API probe:

```text
GET /api/knowledge/status -> 401
{"detail":"无法验证凭据"}
```

This verifies the route is publicly reachable while the data/API surface remains authenticated.

Neo4j from the actual backend container:

```text
neo4j_connectivity=ok
```

Neo4j service:

```text
neo4j:5.26-community
healthy
```

---

## Account boundary

The public Login page includes registration through:

```text
POST /api/auth/register
```

The DB was empty at deployment time, so no existing account or data was reused for the dogfooding session.

---

## What to test first

The first real-note session should deliberately stay small: one well-understood technical note rather than a whole knowledge vault.

Recommended order:

1. register/login;
2. open `/knowledge-lab`;
3. upload one `.md` / `.txt` technical note;
4. start extraction;
5. inspect every pending Claim and its Evidence;
6. confirm only Claims that are actually supported;
7. open Concept Resolution and correct obvious identity mistakes;
8. rebuild/observe projection until graph readiness is caught up;
9. run Association against another source after at least two notes exist;
10. choose confirmed Concepts and test Knowledge Path;
11. record cases that feel forced, missing or genuinely useful.

For the first note, the most important evidence is not latency. It is whether the system's Claim/Evidence/Concept interpretation matches the owner's understanding of a note they know well.

---

## Current non-goals

Still intentionally not part of this deployment:

- anonymous/public data collection;
- telemetry upload;
- cloud sync protocol;
- Graphiti raw episode ingestion;
- Dense embedding dogfooding;
- automatic Claim approval;
- public multi-user beta.

This deployment is an owner-only real-data evaluation environment.
