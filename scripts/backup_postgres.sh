#!/usr/bin/env bash
# Create one portable, checksummed PostgreSQL dump for a Compose deployment.
# Usage: ./scripts/backup_postgres.sh /absolute/path/for/mnemox-backups
set -euo pipefail

usage() {
  echo "Usage: $0 /absolute/path/for/mnemox-backups" >&2
  exit 64
}

if [[ $# -ne 1 || "$1" != /* ]]; then
  usage
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
backup_dir="$1"
db_service="${MNEMOX_POSTGRES_SERVICE:-db}"
db_name="${MNEMOX_POSTGRES_DB:-study_assistant}"
db_user="${MNEMOX_POSTGRES_USER:-postgres}"

if [[ ! "$db_service" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
  echo "Invalid MNEMOX_POSTGRES_SERVICE value." >&2
  exit 65
fi
if [[ ! "$db_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "Invalid MNEMOX_POSTGRES_DB value." >&2
  exit 65
fi
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

umask 077
mkdir -p -- "$backup_dir"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/mnemox-postgres-$timestamp.dump"
metadata_file="${backup_file}.metadata.json"
checksum_file="${backup_file}.sha256"
temporary_file="${backup_file}.partial"
temporary_metadata="${metadata_file}.partial"
temporary_checksum="${checksum_file}.partial"
published=0

for output in "$backup_file" "$metadata_file" "$checksum_file" \
  "$temporary_file" "$temporary_metadata" "$temporary_checksum"; do
  if [[ -e "$output" ]]; then
    echo "Refusing to overwrite an existing backup artifact: $output" >&2
    exit 73
  fi
done

cleanup() {
  rm -f -- "$temporary_file" "$temporary_metadata" "$temporary_checksum"
  if [[ "$published" -eq 0 ]]; then
    rm -f -- "$backup_file" "$metadata_file" "$checksum_file"
  fi
}
trap cleanup EXIT

server_version="$(
  "${compose[@]}" exec -T "$db_service" \
    psql -X -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" \
    -Atqc "SHOW server_version_num"
)"
if [[ ! "$server_version" =~ ^[0-9]+$ ]] \
  || (( server_version < 160000 || server_version >= 170000 )); then
  echo "Backup refused: expected PostgreSQL 16, found server_version_num=$server_version" >&2
  exit 69
fi

"${compose[@]}" exec -T "$db_service" \
  pg_dump -U "$db_user" --format=custom --no-owner --no-privileges \
  --dbname="$db_name" > "$temporary_file"

if [[ ! -s "$temporary_file" ]]; then
  echo "Backup failed: generated file is empty" >&2
  exit 74
fi

# Validate the custom archive before publishing it. Keeping this inside the
# database container means the host only needs Docker, not PostgreSQL clients.
"${compose[@]}" exec -T "$db_service" pg_restore --list \
  < "$temporary_file" > /dev/null

metadata_json="$(
  "${compose[@]}" exec -T "$db_service" \
    psql -X -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" -Atqc \
    "SELECT json_build_object(
       'format_version', 1,
       'created_at_utc', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
       'database_name', current_database(),
       'postgres_server_version_num', current_setting('server_version_num')::integer,
       'alembic_revision', CASE
         WHEN to_regclass('public.alembic_version') IS NULL THEN 'legacy_without_alembic'
         ELSE COALESCE((SELECT version_num FROM alembic_version LIMIT 1), 'missing')
       END,
       'public_table_count', (
         SELECT count(*) FROM information_schema.tables
         WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
       ),
       'row_counts_observed_after_dump', json_build_object(
         'users', CASE WHEN to_regclass('public.users') IS NULL THEN NULL ELSE (SELECT count(*) FROM users) END,
         'materials', CASE WHEN to_regclass('public.materials') IS NULL THEN NULL ELSE (SELECT count(*) FROM materials) END,
         'notes', CASE WHEN to_regclass('public.notes') IS NULL THEN NULL ELSE (SELECT count(*) FROM notes) END,
         'learning_events', CASE WHEN to_regclass('public.learning_events') IS NULL THEN NULL ELSE (SELECT count(*) FROM learning_events) END
       )
     )::text"
)"
if [[ -z "$metadata_json" ]]; then
  echo "Backup failed: could not collect metadata" >&2
  exit 74
fi
printf '%s\n' "$metadata_json" > "$temporary_metadata"

dump_sha256="$(sha256sum "$temporary_file" | awk '{print $1}')"
backup_basename="$(basename -- "$backup_file")"
printf '%s  %s\n' "$dump_sha256" "$backup_basename" > "$temporary_checksum"

chmod 600 "$temporary_file" "$temporary_metadata" "$temporary_checksum"
mv -- "$temporary_file" "$backup_file"
mv -- "$temporary_metadata" "$metadata_file"
mv -- "$temporary_checksum" "$checksum_file"
published=1
trap - EXIT

echo "Backup created: $backup_file"
echo "Metadata: $metadata_file"
echo "Checksum: $checksum_file"
echo "BACKUP_FILE=$backup_file"
