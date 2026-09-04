# Recovery checkpoint — Knowledge Lab Cloud Deploy — 2026-09-04

> Recovery-only branch. **Not merge-ready.** The authoritative checkout remains `/home/cloudcli/projects/mnemox`, which still contains historical dirty/untracked work from earlier stages.

## Deployment result

Public owner dogfooding route:

`https://mnemox.wlohf.com/knowledge-lab`

Final public probes:

- `/` -> HTTP 200
- `/knowledge-lab` -> HTTP 200
- TLS verification -> success
- unauthenticated `/api/knowledge/status` -> HTTP 401
- backend `/health` -> `{"status":"ok"}`
- backend -> Neo4j real connectivity -> ok
- Neo4j 5.26 service -> healthy

## Database safety / migration

Before deployment:

- Alembic version: `20260826_14`
- `users=0`
- `materials=0`
- `concepts=0`
- PostgreSQL custom-format backup created at `/tmp/mnemox-pre-knowledge-lab-20260904.dump` inside the DB container (~221 KiB)

After backend recreate:

- Alembic head: `20260903_22`
- backend health: ok

## Dogfooding runtime flags

- `KNOWLEDGE_V2_ENABLED=true`
- `KNOWLEDGE_LLM_EXTRACTION_ENABLED=true`
- `KNOWLEDGE_EMBEDDING_ENABLED=false`
- `ASSOCIATION_V2_ENABLED=true`
- `KNOWLEDGE_PATH_ENABLED=true`
- `ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED=true`
- `GRAPH_BACKEND=neo4j`
- `NEO4J_GRAPH_ROLLOUT_PERCENT=100`
- `GRAPHITI_ENABLED=false`

These flags are now reproducible through the explicit credential-free `docker-compose.dogfood.yml` overlay.

## Compose boundary

Correct public deployment stack:

```text
docker-compose.yml
+ docker-compose.public.yml
+ docker-compose.dogfood.yml
+ --profile graph
```

Final frontend networks:

- `mnemox_default`
- `web`

Final public backend proxy settings:

- `CORS_ORIGINS=["https://mnemox.wlohf.com"]`
- `TRUST_PROXY_HEADERS=true`
- `TRUSTED_PROXY_HOPS=2`

## Deployment hardening discovered

The development venv had Neo4j installed through spike dependencies, but the production backend image only installed `backend/requirements.txt`. `GRAPH_BACKEND=neo4j` therefore needed the Neo4j Python driver promoted to a formal runtime dependency.

Added:

`neo4j>=6.3,<7`

Rebuilt image evidence:

- Neo4j Python driver `6.3.0`
- `Neo4jGraphStore` import ok
- real connectivity from the deployed backend container ok

`docker-compose.yml` in the authoritative checkout also now passes through `KNOWLEDGE_LLM_EXTRACTION_ENABLED` and `KNOWLEDGE_EMBEDDING_ENABLED`. Because that shared file already contains historical changes, this recovery branch does not claim a clean merge-ready snapshot of it.

## Public override incident / recovery

The first recreate accidentally used only base Compose, temporarily removing the frontend from the external `web` network and resetting public CORS/proxy settings. Public probes returned 502 while the application containers themselves were healthy. No database/user data was affected.

The stack was immediately reconciled with `docker-compose.public.yml`, then made reproducible with `docker-compose.dogfood.yml`. Final public HTTPS probes are green.

## Selected SHA256 inventory from authoritative checkout

- `backend/requirements.txt` `1eafdb349ab30c892eb41e72c19d520d491b4e2e5d832a0f828ee8f3c37c73a6`
- `docker-compose.yml` `07173f13d4df1103d3855c7264ad61106a179080741e245d023e2f57f2ec9c8a`
- `docker-compose.public.yml` `35a901f83a5791913720fb826db51680a9cc6d2033a3858734d52e2689d7c9f0`
- `docker-compose.dogfood.yml` `fd8aaedf75749c518ea8335a7570eb68fbb4ea468523d6dfb0e2a16032d98a86`
- `docs/updates/2026/2026-09-04_mnemox-v2-knowledge-lab-cloud-deploy.md` `e45ce356367d9b8a1cdcee9b910dad04851dbd23c0d19e6f1eb8f731f4ffee08`

## Next action

No further infrastructure changes are required before first dogfooding. The owner can register/login, open `/knowledge-lab`, configure their AI provider if needed, import one well-understood technical note, and evaluate Claim/Evidence/Concept quality before expanding the dataset.
