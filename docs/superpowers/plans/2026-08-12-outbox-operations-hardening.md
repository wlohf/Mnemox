# Projection Outbox Operations Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the durable projection outbox safe under multiple application instances and keep recurring operations snapshots bounded to unfinished queue work.

**Architecture:** Treat `OUTBOX_WORKER_ID` as a deployment-visible prefix rather than the durable heartbeat primary key. Generate one opaque runtime suffix for each worker construction, so an instance can only stop its own heartbeat. Restrict operational aggregate queries to non-processed statuses and support that predicate with a matching index in Alembic, model metadata, and SQLite's lightweight migration path.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async, Alembic, SQLite test database, PostgreSQL production DDL.

---

### Task 1: Isolate Durable Worker Heartbeats Per Runtime Instance

**Files:**
- Modify: `backend/app/services/projection_outbox_worker.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_projection_outbox_worker.py`

- [x] **Step 1: Write a failing multi-instance heartbeat regression**

Create two application workers with the same configured `OUTBOX_WORKER_ID` prefix. Persist a heartbeat for each, stop only the first, then assert the operations snapshot retains one active worker and does not emit `projection_outbox_no_active_worker` while ready work exists.

- [x] **Step 2: Run the regression and verify the configured prefix collision fails**

Run from `backend`:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_projection_outbox_worker.py -k configured_worker_prefix
```

Expected: FAIL because both workers currently persist the exact configured worker ID, so stopping one marks the shared heartbeat stopped.

- [x] **Step 3: Generate an instance-safe heartbeat key at application construction**

Extend the worker ID helper to accept an optional prefix and append hostname, PID, and a random runtime token while preserving the 120-character storage limit. Have `create_projection_outbox_worker` pass the configured value as that prefix. Keep explicit `ProjectionOutboxWorker(worker_id=...)` test and embedding callers deterministic.

- [x] **Step 4: Re-run the focused heartbeat regression**

Run:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_projection_outbox_worker.py -k configured_worker_prefix
```

Expected: PASS, with two durable heartbeat rows and one active peer after the first worker stops.

### Task 2: Bound Operations Aggregates to Live Queue State

**Files:**
- Modify: `backend/app/services/projection_outbox_service.py`
- Modify: `backend/app/models/learner_model.py`
- Modify: `backend/app/database.py`
- Create: `backend/alembic/versions/20260812_06_projection_outbox_operations_performance.py`
- Modify: `backend/tests/test_projection_outbox_operations.py`
- Modify: `backend/tests/test_schema_migration.py`

- [x] **Step 1: Write failing queue-scope and migration-index regressions**

Add an operations test containing a processed historical row plus a pending row and assert `metrics.total` counts only the pending queue row. Extend migration tests to require `ix_projection_outbox_operations_active` from both the PostgreSQL offline DDL and the SQLite lightweight upgrade path.

- [x] **Step 2: Run the focused operations and migration tests to verify they fail**

Run from `backend`:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_projection_outbox_operations.py tests/test_schema_migration.py
```

Expected: FAIL because the existing aggregate has no queue-state predicate and the index does not exist.

- [x] **Step 3: Add the active-state query predicate and aligned index**

Define the operations aggregate over only `pending`, `processing`, and `failed` rows. Add a partial index over `status`, `available_at`, `locked_at`, and `attempts` for the same statuses through a new forward Alembic revision, SQLAlchemy metadata, and SQLite lightweight migrations. Do not edit the already-applied operations migration.

- [x] **Step 4: Re-run the focused operations and migration tests**

Run:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_projection_outbox_operations.py tests/test_schema_migration.py
```

Expected: PASS, including active queue totals and both schema paths.

### Task 3: Verify and Commit the Operations Closure

**Files:**
- Review: all existing Outbox operation files and tests
- Modify: `docs/progress.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/updates/2026/2026-08-09_to_2026-08-09.md`

- [x] **Step 1: Record the deployment semantics**

Update the existing Outbox documentation to state that `OUTBOX_WORKER_ID` is a logical prefix and that each runtime heartbeat ID is unique. Note that the dashboard metrics cover unprocessed queue state and that a real PostgreSQL multi-instance validation remains a release-window requirement.

- [x] **Step 2: Run focused and full backend verification**

Run from `backend`:

```powershell
& .\venv\Scripts\python.exe -m pytest -q tests/test_projection_outbox.py tests/test_projection_outbox_worker.py tests/test_projection_outbox_operations.py tests/test_schema_migration.py
& .\venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass. If the full suite exceeds the environment time limit, retain the focused command result and report the timed-out command rather than claiming full verification.

- [x] **Step 3: Run repository and frontend verification**

Run from the repository root and frontend:

```powershell
git diff --check
npm.cmd run test -- --run
npm.cmd run build
npm.cmd run lint
```

Expected: no whitespace errors; frontend tests, build, and lint pass.

- [x] **Step 4: Independently review the diff and commit only Outbox closure files**

Verify no change exposes user-scoped payloads, writes a shared heartbeat for two live workers, or includes `docs/superpowers/plans/2026-08-09-contextstore-chat-note-migration.md`. Commit the pre-existing Outbox closure plus this hardening in one focused commit.

### Additional hardening completed during review

- Same-version retry-cap drift emits `projection_outbox_retry_policy_config_conflict` as a critical read-only alert and metric; the worker alert scan bypasses policy mutation so the conflict remains visible.
- Active workers whose latest failure is a poll/consumer error (rather than a projection-level row failure) are counted as `error_workers` and emit `projection_outbox_worker_poll_error`.
- Verification evidence: focused Outbox/migration suite `54 passed`; full backend suite `317 passed, 2 warnings, 53 subtests`; frontend `22 files / 67 tests`, build, lint, and Python `compileall` passed.
