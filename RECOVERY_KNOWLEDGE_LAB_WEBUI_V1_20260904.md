# Recovery checkpoint — Knowledge Lab WebUI V1 — 2026-09-04

> Recovery-only branch. **Not merge-ready.**
>
> The authoritative checkout remains `/home/cloudcli/projects/mnemox`, which contains historical dirty/untracked work from earlier stages. This branch preserves the post-Stage-7 Knowledge Lab core and exact recovery metadata; shared files are documented but are not claimed to be a clean full snapshot.

## Scope completed

- authenticated `/knowledge-lab` dogfooding surface;
- existing material upload integration;
- extraction start/status polling;
- bounded owner-scoped Material -> current Source/Revision -> Claim/Evidence/Concept snapshot;
- Claim confirm/reject HTTP boundary using existing `review_claim()` domain service;
- existing Concept Resolution drawer reused;
- Concept inventory + Knowledge Path controls;
- Association V2 + Explainable Multi-hop rendering;
- projection rebuild/runtime/readiness diagnostics;
- no telemetry/data collection added;
- no lab-specific database or Neo4j mutation path.

## Acceptance evidence

Backend Knowledge Lab + adjacent flows:

`39 passed`

Frontend full suite:

`28 test files / 97 tests passed`

Frontend production build:

`passed`

Frontend ESLint:

`passed with max-warnings=0`

`git diff --check`:

- no whitespace errors
- existing `scripts/publish_desktop_release.ps1` LF/CRLF warning only

## SHA256 inventory from authoritative active checkout

- `backend/app/services/knowledge_lab_service.py` `9bc439a5c2d95d0161e8116d25b5eef11b857c73ee07922e58676952bca6a619`
- `backend/app/routers/knowledge.py` `e01ca881d1cf59232e2db9203bf0d45b6197ec315149a67964e695ef607d72ec`
- `backend/tests/test_knowledge_lab.py` `6ada246d8924a8307465644d00f8860db4b70aca3b079767f8394a3c85daec83`
- `frontend/src/services/knowledgeLabApi.ts` `36e544fe1580a644136b832b83320b24129ce4e3e2dea70c8c894cffec78f05a`
- `frontend/src/services/knowledgeLabApi.test.ts` `822c457a53f22315d44e549c012503db59b5abf7c2a5e6d85798a7719e822485`
- `frontend/src/pages/KnowledgeLabPage.tsx` `b33041913379e057752c6bb6467a88ea7caa1e040369ec36a7f08c962046f608`
- `frontend/src/App.tsx` `e4ab8756cafcb309fb8e0485be2c5037a3e24b59793324360ea745cc0b15c815`
- `frontend/src/components/Layout/GlobalNavRail.tsx` `862c69ce928f4e34de04e6b9ad5cec5a766b1bb14fc5436f72a8736be858496c`
- `docs/superpowers/specs/2026-09-04-mnemox-v2-knowledge-lab-webui-contract.md` `c859e0423a466668dee0ebd98b55a5260f537618c87449d5fd0dc55eed2c491f`
- `docs/updates/2026/2026-09-04_mnemox-v2-knowledge-lab-webui.md` `ff5f529d021abca877fe06610b5c2d60c359199ac3d667afdbba5f68b497cd2b`

## Shared-file hooks not represented as a clean merge-ready snapshot

The active checkout also contains the route/API integrations in:

- `backend/app/routers/knowledge.py`
- `frontend/src/App.tsx`
- `frontend/src/components/Layout/GlobalNavRail.tsx`

Those files already contain unrelated historical work, so this recovery branch intentionally does not claim to be a clean standalone PR.

## Deployment boundary

At checkpoint time the DevSpace server already had long-running `mnemox-backend` / `mnemox-frontend` containers plus public reverse-proxy listeners on 80/443. Those containers predate this code. Cloud rebuild/restart and Stage 7 dogfooding flags are the next independent module.
