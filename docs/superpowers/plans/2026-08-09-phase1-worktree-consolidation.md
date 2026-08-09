# Phase 1 Worktree Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Phase 1 learner-model, durable projection, AgentKernel, frontend, and documentation changes into a verified, reviewable, clean Git worktree without expanding Phase 2 scope.

**Architecture:** Treat the current unstaged changes as one candidate release slice, not as independent rewrites. Preserve the relational database as the system of record; verify migration, event/outbox, and projection behavior before validating API/UI consumers. Keep AgentKernel as a guarded prototype and do not add LangGraph, background scheduling, or new product scope during consolidation.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, SQLite/PostgreSQL migration paths, pytest, React, TypeScript, Vite, Vitest, ESLint.

---

### Task 1: Freeze the Change Inventory

**Files:**
- Review: `git status --short`, `git diff --name-status`, `git ls-files --others --exclude-standard`
- Review: `docs/updates/2026/2026-08-04_to_2026-08-05.md`
- Review: `docs/updates/2026/2026-08-06_to_2026-08-06.md`
- Review: `tmp_pg_ddl.sql`

- [x] **Step 1: Record the exact path inventory before modifying it**

Run:

```powershell
git status --short
git diff --name-status
git ls-files --others --exclude-standard
```

Expected: the inventory contains the Phase 1 migration, learner-model, outbox, AgentKernel, frontend, documentation, and historical-document deletion groups.

- [x] **Step 2: Confirm deleted documents are intentionally superseded**

Run:

```powershell
rg -n --glob '!docs/superpowers/plans/2026-08-09-phase1-worktree-consolidation.md' "SETUP.md|UI-UPDATE|AGENT_ARCHITECTURE|system-design|v1.2.0" README.md docs backend frontend
```

Expected: no live navigation or runtime reference points to a deleted document.

- [x] **Step 3: Classify the untracked PostgreSQL DDL capture**

Run:

```powershell
rg -n "tmp_pg_ddl" .
Get-Content -TotalCount 20 tmp_pg_ddl.sql
```

Expected: decide whether the file is a source artifact to retain or an unreferenced generated capture to remove.

### Task 2: Verify Database and Projection Integrity

**Files:**
- Review: `backend/alembic/versions/20260801_00_v13_baseline.py`
- Review: `backend/alembic/versions/20260801_01_phase1_knowledge_fsrs.py`
- Review: `backend/alembic/versions/20260804_01_learner_model_boundary.py`
- Review: `backend/alembic/versions/20260804_02_projection_outbox.py`
- Review: `backend/alembic/versions/20260804_03_legacy_schema_alignment.py`
- Review/Test: `backend/tests/test_schema_migration.py`
- Review/Test: `backend/tests/test_projection_outbox.py`
- Review/Test: `backend/tests/test_projection_outbox_worker.py`

- [x] **Step 1: Run the migration and durable-projection regression suite in the project virtual environment**

Run from `backend`:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_schema_migration.py tests/test_projection_outbox.py tests/test_projection_outbox_worker.py
```

Expected: all selected tests pass; if the 525-row replay test exceeds the interactive time limit, capture the timeout separately and run the remaining tests to completion.

- [x] **Step 2: Check model metadata against Alembic state**

Run from `backend`:

```powershell
& .\venv\Scripts\python.exe -m alembic check
```

Expected: Alembic reports no new upgrade operations.

- [x] **Step 3: Fix only concrete migration or projection defects exposed by the tests**

Modify the smallest affected migration, service, or test file. Add a regression test beside the failing behavior before changing the implementation, then rerun the exact failing test and the full Task 2 suite.

### Task 3: Verify Learner Model and Agent Prototype Boundaries

**Files:**
- Review/Test: `backend/app/models/learner_model.py`
- Review/Test: `backend/app/services/learner_model_service.py`
- Review/Test: `backend/app/services/learner_model_calibration_service.py`
- Review/Test: `backend/app/routers/learner_model.py`
- Review/Test: `backend/app/agents/agent_kernel.py`
- Review/Test: `backend/app/routers/agent.py`
- Test: `backend/tests/test_learner_model_service.py`
- Test: `backend/tests/test_learner_model_api.py`
- Test: `backend/tests/test_learner_model_calibration.py`
- Test: `backend/tests/test_agent_kernel.py`
- Test: `backend/tests/test_north_star_metrics.py`

- [x] **Step 1: Run learner-model, API, calibration, AgentKernel, and metrics regressions**

Run from `backend`:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_learner_model_service.py tests/test_learner_model_api.py tests/test_learner_model_calibration.py tests/test_agent_kernel.py tests/test_north_star_metrics.py
```

Expected: all selected tests pass; the calibration path keeps `collect_more_data` when no holdout data exists.

- [x] **Step 2: Inspect the public boundary for scope creep**

Verify that AgentKernel exposes only read-only tools, wraps tool output as untrusted context, produces draft actions only, and falls back without replacing the existing planner.

- [x] **Step 3: Fix only defects demonstrated by a regression test**

Add a focused test in the matching `backend/tests/test_*.py` module, make the smallest implementation change, and rerun Task 3.

### Task 4: Verify Frontend and Documentation Consumers

**Files:**
- Review/Test: `frontend/src/services/learnerModelApi.ts`
- Review/Test: `frontend/src/services/learnerModelApi.test.ts`
- Review/Test: `frontend/src/pages/learnerModelDisplay.ts`
- Review/Test: `frontend/src/pages/learnerModelDisplay.test.ts`
- Review/Test: `frontend/src/pages/MasteryMapPage.tsx`
- Review: `frontend/src/index.css`
- Review: `README.md`, `backend/README.md`, `docs/README.md`, `docs/progress.md`, `docs/roadmap.md`, `docs/technical.md`

- [x] **Step 1: Run the frontend unit suite, production build, and lint**

Run from `frontend`:

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run lint
```

Expected: tests, TypeScript compilation, production build, and ESLint all exit with code 0.

- [x] **Step 2: Check documentation navigation and stale-reference removal**

Run from the repository root:

```powershell
rg -n --glob '!docs/superpowers/plans/2026-08-09-phase1-worktree-consolidation.md' "SETUP.md|UI-UPDATE|AGENT_ARCHITECTURE|system-design|v1.2.0" README.md docs backend frontend
git diff --check
```

Expected: no stale live links and no whitespace errors; LF/CRLF conversion notices alone do not fail the check.

- [x] **Step 3: Remove the generated DDL capture only if Task 1 proves it is unreferenced**

Delete `tmp_pg_ddl.sql` with an explicit patch, then confirm it no longer appears in `git status --short`.

### Execution Evidence (2026-08-09)

- Initial inventory contained 95 `git status --short` entries. The 29 historical-document removals are explicitly documented as superseded, no live reference points to them, and `tmp_pg_ddl.sql` is already absent and unreferenced.
- The combined migration/projection command exceeded the local 120-second interactive limit without assertion output. Its split verification passed: schema plus worker `14 passed`, outbox non-replay `10 passed`, and the 525-row replay `1 passed`; `alembic check` reported no new upgrade operations.
- A new regression test caught an unmanaged database that already had learner-model/outbox tables but no Alembic version. Those tables are now rejected as post-v1.3 state before automatic baseline stamping; the exact test and the full schema suite passed (`7 passed`).
- Learner model, API, calibration, AgentKernel, and north-star tests all passed when split by timing boundary: service `12`, API `6`, calibration `5`, AgentKernel plus metrics `12`.
- Final frontend verification passed: `22` test files / `67` tests, production build, and lint. `git diff --check` has no whitespace errors; Windows LF/CRLF conversion notices are non-failing.
- Independent review found and the follow-up regression fixed a concurrent note update/delete race: PostgreSQL now locks the owned note before either path touches graph links, and local SQLite serializes writes for the same note through commit. The note-link and multi-user regressions passed (`12 passed`).
- The complete backend suite was rerun after that fix and passed: `290 passed, 2 warnings, 53 subtests passed` in `1420.51s`. The two warnings are existing Pydantic and `datetime.utcnow()` deprecations outside this slice.
- An isolated SQLite database upgraded through `20260809_04`, then passed `alembic check` with no new upgrade operations. The existing local development database remains intentionally at `20260804_03` and was not modified during consolidation.
- Browser preflight used an isolated Playwright session: `/mastery` correctly redirected to login and the desktop login page rendered with zero console errors. No documented local test account existed, so authenticated MasteryMap switching, filtering, pagination, and override flows remain explicitly unexecuted rather than borrowing an existing session. Artifacts are in ignored `output/playwright/`.

### Task 5: Consolidate, Review, and Commit

**Files:**
- Review: all changed paths from Task 1
- Create: `docs/superpowers/plans/2026-08-09-phase1-worktree-consolidation.md`

- [x] **Step 1: Inspect the final diff by logical group**

Run:

```powershell
git diff --stat
git diff --check
git status --short
```

Expected: only intended implementation, tests, documents, and explicitly approved historical deletions remain.

- [x] **Step 2: Perform an independent code review before staging**

Review learner-model/outbox/worker, AgentKernel, migration, and frontend changes for authorization, transaction, user-isolation, compatibility, and test gaps. Fix Critical and Important findings, then rerun the affected verification commands.

- [x] **Step 3: Create focused commits in dependency order**

Stage and commit in this order:

```powershell
git add backend/alembic backend/app backend/init_db.py backend/run_migrations.py backend/calibrate_learner_model.py backend/tests docker-compose.yml .env.example backend/Dockerfile backend/README.md
git commit -m "feat: add learner model projection foundation"

git add frontend/src
git commit -m "feat: expose learner model evidence workspace"

git add README.md docs SETUP.md UI-UPDATE.md UI-UPDATE-V2.md release-notes-v1.0.3.md release-notes-v1.0.4.md release-notes-v1.0.5.md release-notes-v1.0.6.md release-notes-v1.0.7.md release-notes-v1.0.8.md release-notes-v1.0.9.md release-notes-v1.2.0.md
git commit -m "docs: consolidate phase one architecture and operations"
```

Expected: commits are reviewable, the working tree is clean except for intentionally preserved local runtime files ignored by Git, and no push is performed without a separate instruction.

- [x] **Step 4: Record final verification evidence**

Run:

```powershell
git status --short
git log --oneline -3
```

Expected: an empty status and the focused consolidation commits at the top of the branch.

### Final Local Commit Evidence (2026-08-09)

- `ad94e68 feat: add learner model projection foundation` contains the backend foundation plus the consolidation fixes, migration, and regressions.
- `1041d09 feat: expose learner model evidence workspace` contains the MasteryMap evidence workspace and its frontend tests.
- `docs: consolidate phase one architecture and operations` contains documentation navigation, current architecture records, and superseded historical document removals.
- Final `git status --short` was empty and `git diff --check HEAD` passed. No remote push was performed.
