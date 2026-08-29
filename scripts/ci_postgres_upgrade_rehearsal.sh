#!/usr/bin/env bash
# CI-only PostgreSQL 16 upgrade/backup/restore rehearsal. It creates and drops
# databases whose names are fixed to the mnemox_ci_ namespace.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
python_bin="${MNEMOX_PYTHON:-python}"
url_prefix="${POSTGRES_REHEARSAL_URL_PREFIX:-}"
source_db="mnemox_ci_upgrade_source"
restore_db="mnemox_ci_upgrade_restore"

if [[ "$url_prefix" != postgresql+asyncpg://* ]]; then
  echo "POSTGRES_REHEARSAL_URL_PREFIX must be a postgresql+asyncpg URL without a database name" >&2
  exit 64
fi
for database_name in "$source_db" "$restore_db"; do
  if [[ "$database_name" != mnemox_ci_* ]]; then
    echo "Unsafe CI rehearsal database name: $database_name" >&2
    exit 65
  fi
done

temporary_dir="$(mktemp -d)"
dump_file="$temporary_dir/historical.dump"

cleanup() {
  dropdb --if-exists --force "$restore_db" >/dev/null 2>&1 || true
  dropdb --if-exists --force "$source_db" >/dev/null 2>&1 || true
  rm -f -- "$dump_file"
  rmdir -- "$temporary_dir" 2>/dev/null || true
}
trap cleanup EXIT

dropdb --if-exists --force "$restore_db" >/dev/null 2>&1 || true
dropdb --if-exists --force "$source_db" >/dev/null 2>&1 || true
createdb --template=template0 --encoding=UTF8 "$source_db"

(
  cd "$repo_root/backend"
  DATABASE_URL="$url_prefix/$source_db" \
    "$python_bin" -m alembic upgrade 20260801_01
)

psql -X -v ON_ERROR_STOP=1 -d "$source_db" <<'SQL'
INSERT INTO users (id, username, email, hashed_password, is_active)
VALUES (91001, 'pg-upgrade-user', 'pg-upgrade@example.test', 'acceptance-only', true);

INSERT INTO materials (id, user_id, title, content, content_status)
VALUES (92001, 91001, 'Historical PostgreSQL material', 'preserve this material', 'ready');

INSERT INTO notes (id, user_id, material_id, title, content, tags, note_type)
VALUES (93001, 91001, 92001, 'Historical PostgreSQL note', 'preserve this note', '["migration"]', 'text');

INSERT INTO concepts (id, user_id, name, name_normalized, mastery, source)
VALUES (94001, 91001, 'Historical mastery', 'historical mastery', 72.5, 'acceptance');

INSERT INTO learning_events (
  id, user_id, event_type, event_category, source, dedupe_key,
  event_data, timestamp, material_id, note_id
)
VALUES (
  95001, 91001, 'practice.answer', 'practice', 'postgres-upgrade-rehearsal',
  'pg-upgrade-rehearsal:95001', '{"concept_id": 94001, "score": 0.725}',
  '2026-08-01 12:00:00', 92001, 93001
);
SQL

pg_dump --format=custom --no-owner --no-privileges \
  --dbname="$source_db" --file="$dump_file"
pg_restore --list "$dump_file" >/dev/null

createdb --template=template0 --encoding=UTF8 "$restore_db"
pg_restore --exit-on-error --single-transaction --no-owner --no-privileges \
  --dbname="$restore_db" "$dump_file"

(
  cd "$repo_root/backend"
  DATABASE_URL="$url_prefix/$restore_db" "$python_bin" run_migrations.py
  POSTGRES_UPGRADE_REHEARSAL_DATABASE_URL="$url_prefix/$restore_db" \
    "$python_bin" -m pytest -q tests/acceptance/test_postgres_upgrade_rehearsal.py
  DATABASE_URL="$url_prefix/$restore_db" "$python_bin" -m alembic check
)

echo "CI PostgreSQL historical upgrade and dump/restore rehearsal passed."
