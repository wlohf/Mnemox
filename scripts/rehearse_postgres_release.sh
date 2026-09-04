#!/usr/bin/env bash
# Back up the configured deployment, restore it to a disposable database, and
# run the current migration chain there. The source database is never upgraded.
# Usage: ./scripts/rehearse_postgres_release.sh /absolute/path/for/backups
set -euo pipefail

if [[ $# -ne 1 || "$1" != /* ]]; then
  echo "Usage: $0 /absolute/path/for/backups" >&2
  exit 64
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backup_output="$($script_dir/backup_postgres.sh "$1")"
printf '%s\n' "$backup_output"

backup_file="$(printf '%s\n' "$backup_output" | sed -n 's/^BACKUP_FILE=//p')"
if [[ -z "$backup_file" || "$backup_file" != /* || ! -f "$backup_file" ]]; then
  echo "Release rehearsal failed: backup script did not return a valid archive path" >&2
  exit 1
fi

"$script_dir/verify_postgres_backup.sh" --upgrade "$backup_file"

echo "PostgreSQL release rehearsal passed."
echo "The source database was backed up but not upgraded."
