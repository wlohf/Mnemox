#!/usr/bin/env bash
# Restore a Mnemox dump into a disposable database and optionally rehearse the
# current code's production migration against that restored copy.
# Usage: ./scripts/verify_postgres_backup.sh [--upgrade] /absolute/path/to/*.dump
set -euo pipefail

usage() {
  echo "Usage: $0 [--upgrade] /absolute/path/to/mnemox-postgres-*.dump" >&2
  exit 64
}

upgrade=0
if [[ "${1:-}" == "--upgrade" ]]; then
  upgrade=1
  shift
fi
if [[ $# -ne 1 || "$1" != /* || ! -f "$1" ]]; then
  usage
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
backup_file="$1"
checksum_file="${backup_file}.sha256"
metadata_file="${backup_file}.metadata.json"
db_service="${MNEMOX_POSTGRES_SERVICE:-db}"
db_user="${MNEMOX_POSTGRES_USER:-postgres}"
backend_service="${MNEMOX_BACKEND_SERVICE:-backend}"

for service_value in "$db_service" "$backend_service"; do
  if [[ ! "$service_value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "Invalid Compose service name." >&2
    exit 65
  fi
done
if [[ ! "$db_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "Invalid MNEMOX_POSTGRES_USER value." >&2
  exit 65
fi

compose=(
  docker compose
  --project-directory "$repo_root"
  -f "$repo_root/docker-compose.yml"
  -f "$repo_root/docker-compose.public.yml"
)
verify_db="mnemox_restore_verify_$(date -u +%Y%m%d%H%M%S)_$RANDOM"
created=0

cleanup() {
  if [[ "$created" -eq 1 ]]; then
    "${compose[@]}" exec -T "$db_service" \
      dropdb -U "$db_user" --if-exists --force "$verify_db" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ ! -f "$checksum_file" ]]; then
  echo "Restore verification refused: checksum sidecar is missing: $checksum_file" >&2
  exit 66
fi
expected_sha256="$(awk 'NR == 1 { print $1 }' "$checksum_file")"
if [[ ! "$expected_sha256" =~ ^[0-9A-Fa-f]{64}$ ]]; then
  echo "Restore verification refused: checksum sidecar is malformed" >&2
  exit 65
fi
actual_sha256="$(sha256sum "$backup_file" | awk '{print $1}')"
if [[ "${expected_sha256,,}" != "$actual_sha256" ]]; then
  echo "Restore verification failed: SHA-256 mismatch" >&2
  exit 1
fi
echo "SHA-256 verified: $actual_sha256"

# Reject a truncated or non-custom archive before creating any database.
"${compose[@]}" exec -T "$db_service" pg_restore --list \
  < "$backup_file" > /dev/null

"${compose[@]}" exec -T "$db_service" \
  createdb -U "$db_user" --template=template0 --encoding=UTF8 "$verify_db"
created=1

pg_restore_output="$(
  "${compose[@]}" exec -T "$db_service" \
    pg_restore -U "$db_user" --exit-on-error --single-transaction \
      --no-owner --no-privileges --dbname="$verify_db" \
    < "$backup_file" 2>&1
)" || {
  echo "$pg_restore_output" >&2
  exit 1
}

snapshot_sql="
SELECT concat_ws('|',
  CASE
    WHEN to_regclass('public.alembic_version') IS NULL THEN 'legacy_without_alembic'
    ELSE COALESCE((SELECT version_num FROM alembic_version LIMIT 1), 'missing')
  END,
  (SELECT count(*) FROM information_schema.tables
   WHERE table_schema = 'public' AND table_type = 'BASE TABLE'),
  CASE WHEN to_regclass('public.users') IS NULL THEN -1 ELSE (SELECT count(*) FROM users) END,
  CASE WHEN to_regclass('public.materials') IS NULL THEN -1 ELSE (SELECT count(*) FROM materials) END,
  CASE WHEN to_regclass('public.notes') IS NULL THEN -1 ELSE (SELECT count(*) FROM notes) END,
  CASE WHEN to_regclass('public.learning_events') IS NULL THEN -1 ELSE (SELECT count(*) FROM learning_events) END
)"

read_snapshot() {
  "${compose[@]}" exec -T "$db_service" \
    psql -X -v ON_ERROR_STOP=1 -U "$db_user" -d "$verify_db" \
      -Atqc "$snapshot_sql"
}

before_snapshot="$(read_snapshot)"
IFS='|' read -r before_revision before_tables before_users before_materials \
  before_notes before_events <<< "$before_snapshot"
if [[ "$before_users" == "-1" ]]; then
  echo "Restore verification failed: users table is missing" >&2
  exit 1
fi

echo "Restore completed in disposable database: $verify_db"
echo "Restored revision: $before_revision"
echo "Restored public tables: $before_tables"
echo "Restored stable counts: users=$before_users materials=$before_materials notes=$before_notes learning_events=$before_events"
if [[ -f "$metadata_file" ]]; then
  echo "Backup metadata found: $metadata_file"
fi

run_backend_against_verify_db() {
  "${compose[@]}" run --rm --no-deps -T \
    -v "$repo_root/backend/app:/app/app:ro" \
    -v "$repo_root/backend/alembic:/app/alembic:ro" \
    -v "$repo_root/backend/alembic.ini:/app/alembic.ini:ro" \
    -v "$repo_root/backend/run_migrations.py:/app/run_migrations.py:ro" \
    -e "MNEMOX_REHEARSAL_DB=$verify_db" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    "$backend_service" \
    sh -eu -c '
      case "$MNEMOX_REHEARSAL_DB" in
        mnemox_restore_verify_*) ;;
        *) echo "Unsafe rehearsal database name" >&2; exit 65 ;;
      esac
      case "$DATABASE_URL" in
        postgresql+asyncpg://*/*) ;;
        *) echo "Backend DATABASE_URL is not PostgreSQL" >&2; exit 69 ;;
      esac
      export DATABASE_URL="${DATABASE_URL%/*}/${MNEMOX_REHEARSAL_DB}"
      export OUTBOX_WORKER_ENABLED=false
      export AGENT_RUNTIME_SCHEDULER_ENABLED=false
      exec "$@"
    ' rehearsal-shell "$@"
}

if [[ "$upgrade" -eq 1 ]]; then
  echo "Running the production migration entrypoint against the disposable restore..."
  run_backend_against_verify_db python run_migrations.py
  run_backend_against_verify_db python -m alembic check

  expected_head="$(
    run_backend_against_verify_db python -c \
      'from alembic.config import Config; from alembic.script import ScriptDirectory; c=Config("/app/alembic.ini"); c.set_main_option("script_location", "/app/alembic"); print(ScriptDirectory.from_config(c).get_current_head())'
  )"
  if [[ ! "$expected_head" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "Upgrade verification failed: could not resolve the code's Alembic head" >&2
    exit 1
  fi

  after_snapshot="$(read_snapshot)"
  IFS='|' read -r after_revision after_tables after_users after_materials \
    after_notes after_events <<< "$after_snapshot"
  if [[ "$after_revision" != "$expected_head" ]]; then
    echo "Upgrade verification failed: database=$after_revision code=$expected_head" >&2
    exit 1
  fi
  if [[ "$before_users|$before_materials|$before_notes|$before_events" \
    != "$after_users|$after_materials|$after_notes|$after_events" ]]; then
    echo "Upgrade verification failed: stable row counts changed" >&2
    echo "Before: users=$before_users materials=$before_materials notes=$before_notes learning_events=$before_events" >&2
    echo "After: users=$after_users materials=$after_materials notes=$after_notes learning_events=$after_events" >&2
    exit 1
  fi

  echo "Upgrade rehearsal verified at Alembic head: $after_revision"
  echo "Post-upgrade public tables: $after_tables"
  echo "Stable row counts preserved."
fi

echo "Disposable verification database will now be removed."
