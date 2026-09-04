# Recovery checkpoint: onboarding UTC hotfix (2026-09-04)

Recovery-only checkpoint; not merge-ready. Active checkout remains historically dirty.

## Incident
After first cloud login, `POST /api/system/onboarding-dismissed` returned HTTP 500 on PostgreSQL. The traceback showed asyncpg rejecting an aware UTC datetime for `user_memories.last_seen_at`, whose column is `TIMESTAMP WITHOUT TIME ZONE`:

`can't subtract offset-naive and offset-aware datetimes`

## Fix
`backend/app/routers/system.py`
- `_mark_system_memory()` now uses canonical `utc_now_db()` for database writes (naive UTC).
- the string-valued marker uses `to_utc_iso(now)` so API/business text remains RFC3339 UTC with `Z`.

`backend/tests/test_multi_user_isolation.py`
- onboarding marker regression now asserts `last_seen_at.tzinfo is None` and marker text ends with `Z`.

## Verification
- `pytest -q tests/test_multi_user_isolation.py -k onboarding_auto_show_marker` => `1 passed, 8 deselected`
- `pytest -q tests/test_knowledge_lab.py tests/test_multi_user_isolation.py` => `13 passed`
- repository scan found no other direct `last_seen_at = datetime.now(timezone.utc)` assignments.
- `git diff --check -- app/routers/system.py tests/test_multi_user_isolation.py` => clean.

## Active-checkout SHA256
- `backend/app/routers/system.py` `1ef4d2fdf031d3edce55415954815682634300a8d22ff3a8eb3abc1914ecbf78`
- `backend/tests/test_multi_user_isolation.py` `0e8d96c6cb78c0a9d392d0a32350b0a61e6e9014cf5385d1ef54427d278cc502`
