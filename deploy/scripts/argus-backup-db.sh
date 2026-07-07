#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/argus"
BACKUP_DIR="/opt/argus/backups"
ENV_FILE="$PROJECT_DIR/.env.local"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | cut -d '=' -f2-)"

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL not found"
    exit 1
fi

DATE="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/argus-db-$DATE.dump"

/usr/lib/postgresql/18/bin/pg_dump "$DATABASE_URL" --format=custom --no-owner --no-privileges --file="$OUT"

chmod 600 "$OUT"

find "$BACKUP_DIR" -type f -name "argus-db-*.dump" -mtime +14 -delete

echo "Backup created: $OUT"
