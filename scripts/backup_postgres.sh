#!/usr/bin/env bash
# Create one recoverable PostgreSQL dump for a Docker Compose deployment.
# Usage: ./scripts/backup_postgres.sh /absolute/path/for/mnemox-backups
set -euo pipefail

if [[ $# -ne 1 || "$1" != /* ]]; then
  echo "Usage: $0 /absolute/path/for/mnemox-backups" >&2
  exit 64
fi

backup_dir="$1"
mkdir -p -- "$backup_dir"
umask 077

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/mnemox-postgres-$timestamp.dump"
temporary_file="$backup_file.partial"

if [[ -e "$backup_file" || -e "$temporary_file" ]]; then
  echo "Refusing to overwrite an existing backup: $backup_file" >&2
  exit 73
fi

cleanup() {
  rm -f -- "$temporary_file"
}
trap cleanup EXIT

docker compose -f docker-compose.yml -f docker-compose.public.yml \
  exec -T db pg_dump -U postgres -Fc -d study_assistant > "$temporary_file"

if [[ ! -s "$temporary_file" ]]; then
  echo "Backup failed: generated file is empty" >&2
  exit 74
fi

mv -- "$temporary_file" "$backup_file"
sha256sum "$backup_file" > "$backup_file.sha256"
trap - EXIT

echo "Backup created: $backup_file"
echo "Checksum: $backup_file.sha256"
