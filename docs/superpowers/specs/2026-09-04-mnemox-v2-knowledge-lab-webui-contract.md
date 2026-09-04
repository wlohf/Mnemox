# Mnemox V2 — Cloud Knowledge Lab WebUI Dogfooding Contract

> Date: 2026-09-04  
> Status: implementation contract  
> Goal: give the project owner one cloud-accessible place to import real technical notes and evaluate the completed Stage 7 knowledge/graph pipeline end-to-end.

## 1. Why this page exists

Stage 7 engineering acceptance is complete, but synthetic correctness does not answer the product question:

> When a real Chinese/English technical note is imported, are the extracted Claims, Concepts, relations, associations and learning paths actually useful?

The existing UI already contains pieces of the workflow, but they are distributed across the conversation layout, material sidebar, resolution drawer and mastery pages. A dogfooding session needs one bounded lab that makes the pipeline observable without exposing database consoles or internal graph tooling.

Knowledge Lab is therefore a **product-evaluation surface**, not a new canonical subsystem.

---

## 2. V1 workflow

```text
Upload technical note
  -> Knowledge extraction
  -> inspect grounded Claims + Evidence
  -> confirm/reject Claims
  -> resolve Concept candidates
  -> inspect confirmed Concepts
  -> Association V2 query
  -> Knowledge/Learning Path query
  -> runtime/readiness diagnostics
  -> human judgement recorded manually for now
```

The V1 page is intentionally for the owner/dogfooding user. It is authenticated and uses the same user isolation as the normal product.

---

## 3. Data ownership rule

Knowledge Lab does not create an alternate lab database.

It reads/writes only the existing canonical product objects:

- Material;
- KnowledgeSource / Revision / Unit;
- Claim / ClaimEvidence;
- EntityResolutionCandidate;
- ClaimConceptLink / Concept;
- existing projection queues;
- existing Association V2 / Knowledge Path services.

Any claim confirmation/rejection must call the existing `review_claim()` domain service so projection lifecycle and validation remain identical to normal product behavior.

---

## 4. New API surface

Two small authenticated API additions are allowed because the underlying domain service already exists and the current UI cannot complete the review loop.

### Material knowledge snapshot

```http
GET /api/knowledge/materials/{material_id}/claims?review_status=all
```

Returns a bounded, owner-scoped inspection view:

- current source/revision only;
- active Claims;
- Claim review status/kind/confidence;
- bounded grounded Evidence excerpts;
- confirmed/pending Concept links with Concept names;
- no other user's rows.

This is an inspection endpoint, not a graph backend endpoint. It must not expose Neo4j IDs/Cypher or raw vector data.

### Claim review

```http
POST /api/knowledge/claims/{claim_id}/review
```

Body:

```json
{"review_status":"confirmed"}
```

Allowed statuses for WebUI V1:

```text
confirmed
rejected
```

The domain service still enforces that a Claim without Evidence cannot be confirmed.

---

## 5. Existing API reused by the page

Knowledge Lab should reuse rather than duplicate:

- `POST /api/materials/upload`;
- `GET /api/materials/`;
- `GET /api/knowledge/materials/{id}/extraction`;
- `POST /api/knowledge/materials/{id}/extract`;
- `GET /api/knowledge/extraction-runs/{id}`;
- resolution candidate APIs;
- `GET /api/concepts`;
- `GET /api/knowledge/status`;
- `POST /api/knowledge/associate`;
- `POST /api/knowledge/learning-path`;
- optional `/api/memory/temporal-graph/*` only for diagnostics/advanced testing later.

---

## 6. WebUI sections

Route:

```text
/knowledge-lab
```

### A. Runtime banner

Show:

- Knowledge V2 enabled/disabled;
- source / Claim / pending resolution counts;
- configured/effective graph backend;
- Neo4j primary/serving readiness;
- projection caught-up state;
- clear explanation if Knowledge Path is unavailable.

This avoids making the user infer backend state from a 503.

### B. Import + material selection

- upload `.md`, `.txt`, `.pdf`, `.docx` through the existing material endpoint;
- list recent materials;
- select one material as the current evaluation subject;
- trigger/retry deterministic or configured extraction;
- refresh extraction status.

### C. Claim review

For selected material show each Claim with:

- statement;
- kind;
- confidence;
- review status;
- Evidence excerpt(s);
- Concept links.

Actions:

```text
Confirm
Reject
```

No bulk auto-confirm in V1. Real dogfooding needs the user to notice extraction mistakes.

### D. Concept resolution

Reuse the existing Knowledge Resolution workflow, scoped to the selected material.

### E. Concept inventory

Show confirmed/current user's concepts with mastery/link counts. Allow selecting start and target Concepts for Knowledge Path.

### F. Association test

Free-text query + optional current material source context.

Show:

- related Claim;
- source;
- score/confidence;
- relation/shared structure;
- grounded Evidence;
- Stage 7 multi-hop explanation when available;
- degraded/runtime diagnostics in a collapsed technical panel.

### G. Knowledge Path test

Allow one or more start concepts and one target.

Show:

- path depth/score;
- concept sequence;
- mastered/weak/unseen state;
- each relation/provenance status;
- runtime backend / route reason;
- clear no-path or capability-unavailable state.

---

## 7. Human evaluation boundary

V1 does **not** upload telemetry or other people's data.

The page is used by the project owner with their own notes. Human evaluation can initially be recorded manually in an evaluation document/spreadsheet later.

Useful observations:

```text
Claim correct?
Evidence actually supports Claim?
Concept identity correct?
Relation correct?
Association useful or forced?
Learning Path useful?
Explanation useful?
No-path reasonable?
Latency/fallback acceptable?
```

Do not automatically turn clicks into training labels in V1.

---

## 8. Cloud deployment boundary

The preferred dogfooding topology is:

```text
Browser
  -> existing Mnemox frontend
  -> existing FastAPI backend
  -> PostgreSQL
  -> Chroma / Sparse
  -> optional Neo4j (--profile graph)
```

For Stage 7 graph testing the cloud server may explicitly enable:

```text
KNOWLEDGE_V2_ENABLED=true
ASSOCIATION_V2_ENABLED=true
KNOWLEDGE_PATH_ENABLED=true
ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED=true
GRAPH_BACKEND=neo4j
GRAPHITI_ENABLED=false   # keep Temporal experiment separate unless specifically testing it
```

Neo4j projection readiness must still gate graph-native execution; enabling a flag must not bypass caught-up checks.

Graphiti remains off during ordinary real-note Knowledge Lab testing because note ingestion is testing the knowledge graph, not temporal memory.

---

## 9. Acceptance criteria

Before calling Knowledge Lab V1 usable:

- authenticated `/knowledge-lab` route exists;
- material upload works through the existing endpoint;
- a selected material can be extracted and its status refreshed;
- pending/confirmed/rejected Claims can be inspected with Evidence;
- Claim confirm/reject works through domain service;
- Concept Resolution is reachable from the selected material;
- concepts can be loaded and selected;
- Association V2 result is readable;
- Knowledge Path result is readable;
- runtime/readiness state is visible;
- other-user data cannot be accessed through snapshot/review endpoints;
- API errors do not leak backend credentials/query text;
- frontend tests/build/lint remain green;
- backend knowledge-lab tests remain green;
- a recovery checkpoint is created before cloud deployment work continues.

---

## 10. Non-goals

Not in Knowledge Lab V1:

- public anonymous signup;
- telemetry/product analytics collection;
- payments;
- cloud sync protocol;
- multi-tenant admin console;
- auto-accepting extracted knowledge;
- editing Neo4j directly;
- Graphiti raw episode ingestion;
- replacing the normal Mnemox UI.

This is the smallest real-data evaluation surface needed after Stage 7.
