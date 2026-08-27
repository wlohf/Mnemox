#!/usr/bin/env bash
# Restore one Mnemox PostgreSQL backup into a disposable database and validate it.
# Usage: ./scripts/verify_postgres_backup.sh /absolute/path/to/mnemox-postgres-*.dump
set -euo pipefail

if [[ $# -ne 1 || "$1" != /* || ! -f "$1" ]]; then
  echo "Usage: $0 /absolute/path/to/mnemox-postgres-*.dump" >&2
  exit 64
fi

backup_file="$1"
checksum_file="${backup_file}.sha256"
compose=(docker compose -f docker-compose.yml -f docker-compose.public.yml)
verify_db="mnemox_restore_verify_$(date -u +%Y%m%d%H%M%S)_$RANDOM"
created=0

cleanup() {
  if [[ "$created" -eq 1 ]]; then
    "${compose[@]}" exec -T db dropdb -U postgres --if-exists "$verify_db" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ -f "$checksum_file" ]]; then
  sha256sum --check "$checksum_file"
else
  echo "Warning: checksum sidecar not found; archive structure will still be verified." >&2
fi

"${compose[@]}" exec -T db createdb -U postgres -T template0 "$verify_db"
created=1

# Feed the archive over stdin so the temporary database remains inside the
# existing database container and no database port needs to be exposed.
pg_restore_output="$("${compose[@]}" exec -T db pg_restore -U postgres --exit-on-error -d "$verify_db" < "$backup_file" 2>&1)" || {
  echo "$pg_restore_output" >&2
  exit 1
}

user_table_exists="$("${compose[@]}" exec -T db psql -U postgres -d "$verify_db" -Atqc "SELECT to_regclass('public.users') IS NOT NULL;")"
if [[ "$user_table_exists" != "t" ]]; then
  echo "Restore verification failed: users table is missing" >&2
  exit 1
fi

table_count="$("${compose[@]}" exec -T db psql -U postgres -d "$verify_db" -Atqc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")"
alembic_version="$("${compose[@]}" exec -T db psql -U postgres -d "$verify_db" -Atqc "SELECT CASE WHEN to_regclass('public.alembic_version') IS NULL THEN 'legacy_without_alembic' ELSE (SELECT version_num FROM alembic_version LIMIT 1) END;")"

echo "Restore verified in disposable database: $verify_db"
echo "Public tables: $table_count"
echo "Alembic version: $alembic_version"
echo "The disposable verification database will now be removed."
