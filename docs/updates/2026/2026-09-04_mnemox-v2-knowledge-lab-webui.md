# 2026-09-04 — Mnemox Knowledge Lab WebUI V1

## Purpose

Stage 7 engineering is complete. Knowledge Lab is the first post-Stage-7 dogfooding surface for importing the project owner's real technical notes and inspecting the actual canonical knowledge pipeline end-to-end.

It is not a second database or a fake Demo dataset.

## V1 workflow

```text
Upload real note
  -> Knowledge extraction
  -> inspect Claim + Evidence
  -> confirm/reject Claim
  -> Concept Resolution
  -> inspect Concept inventory
  -> rebuild/observe projection
  -> Association V2
  -> Knowledge/Learning Path
  -> Multi-hop explanation/runtime diagnostics
```

## Backend additions

### `knowledge_lab_service.py`

Adds a bounded owner-scoped material knowledge snapshot:

- current active KnowledgeSource only;
- current KnowledgeSourceRevision only;
- active Claims;
- pending/confirmed/rejected review state;
- max 3 grounded Evidence excerpts per Claim;
- bounded Concept links with review state;
- cross-user rows are rejected;
- no Neo4j IDs, Cypher or vector payloads.

### New authenticated API boundaries

```text
GET  /api/knowledge/materials/{material_id}/claims
POST /api/knowledge/claims/{claim_id}/review
```

Claim review reuses the existing `review_claim()` domain service. Therefore:

- a Claim without Evidence cannot be confirmed;
- owner checks are unchanged;
- projection lifecycle is unchanged;
- the Lab does not create a special review path.

## Frontend additions

New route:

```text
/knowledge-lab
```

The page is available as an advanced item under the Knowledge navigation group.

Sections:

1. Runtime/readiness banner
2. Material upload + extraction status
3. Claim/Evidence review
4. Concept Resolution drawer
5. Concept inventory + Knowledge Path
6. Association V2 + Explainable Multi-hop
7. technical diagnostics collapses for runtime investigation

The page reuses the existing material upload, extraction, resolution, projection, Association and Knowledge Path APIs.

## Safety/product boundaries

- authenticated only;
- no anonymous/public upload;
- no telemetry/data collection added;
- no bulk auto-confirm;
- no direct Neo4j editing;
- no Graphiti raw episode ingestion;
- real human evaluation remains manual for V1;
- Graphiti remains off during ordinary knowledge-note dogfooding unless explicitly tested separately.

## Acceptance evidence

Backend Knowledge Lab + adjacent knowledge flows:

```text
39 passed
```

Frontend full suite after adding Lab API tests:

```text
28 test files passed
97 tests passed
```

Frontend production build:

```text
passed
```

Frontend ESLint:

```text
passed with max-warnings=0
```

`git diff --check`:

```text
no whitespace errors
existing PowerShell LF/CRLF warning only
```

## Cloud readiness observation

The current DevSpace server already has a public reverse-proxy entry on ports 80/443 and long-running `mnemox-backend` / `mnemox-frontend` containers. The application containers predate this Knowledge Lab implementation, so a separate deployment step is required after the recovery checkpoint.

The next operation is therefore:

```text
Knowledge Lab recovery checkpoint
  -> rebuild/restart backend + frontend
  -> enable Stage 7 dogfooding flags on the server
  -> verify login / /knowledge-lab / API health
  -> import the owner's real notes
```

Cloud deployment is deliberately treated as a separate module from WebUI code implementation so rollback remains clear.
