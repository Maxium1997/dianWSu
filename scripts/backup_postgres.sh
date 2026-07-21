#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_dir="${BACKUP_DIR:-$project_root/backups}"

mkdir -p "$backup_dir"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup_file="$backup_dir/dianwsu-$timestamp.sql.gz"

cd "$project_root"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$backup_file"
echo "Created PostgreSQL backup: $backup_file"
