#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.local}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups/db}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

read_env_value() {
    local key="$1"
    local file="$2"
    local line
    local value

    line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
    value="${line#*=}"
    value="${value%$'\r'}"

    # Remove optional surrounding quotes.
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"

    printf '%s' "$value"
}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" || true

DATABASE_URL="${DATABASE_URL:-}"

if [[ -z "$DATABASE_URL" && -f "$ENV_FILE" ]]; then
    DATABASE_URL="$(read_env_value "DATABASE_URL" "$ENV_FILE")"
fi

[[ -n "$DATABASE_URL" ]] || fail "DATABASE_URL is not configured"

PG_DUMP="${PG_DUMP:-}"
if [[ -z "$PG_DUMP" ]]; then
    if [[ -x "/usr/lib/postgresql/18/bin/pg_dump" ]]; then
        PG_DUMP="/usr/lib/postgresql/18/bin/pg_dump"
    else
        PG_DUMP="$(command -v pg_dump || true)"
    fi
fi

[[ -n "$PG_DUMP" && -x "$PG_DUMP" ]] || fail "pg_dump not found"
command -v gzip >/dev/null 2>&1 || fail "gzip not found"

timestamp="$(date +%Y%m%d-%H%M%S)"
final_file="$BACKUP_DIR/argus-postgres-$timestamp.sql.gz"
tmp_file="$(mktemp "$BACKUP_DIR/.argus-postgres-$timestamp.XXXXXX.sql.gz.tmp")"

cleanup() {
    if [[ -n "${tmp_file:-}" && -f "$tmp_file" ]]; then
        rm -f "$tmp_file"
    fi
}
trap cleanup EXIT

log "Starting PostgreSQL backup"

if ! "$PG_DUMP" \
    --dbname="$DATABASE_URL" \
    --format=plain \
    --no-owner \
    --no-privileges \
    | gzip -c > "$tmp_file"; then
    fail "pg_dump failed; temporary backup removed"
fi

if [[ ! -s "$tmp_file" ]]; then
    fail "backup is empty; temporary backup removed"
fi

if ! gzip -t "$tmp_file"; then
    fail "gzip integrity check failed; temporary backup removed"
fi

mv "$tmp_file" "$final_file"
tmp_file=""

chmod 600 "$final_file"

# Remove stale broken files from previous failed runs.
find "$BACKUP_DIR" -maxdepth 1 -type f -name ".argus-postgres-*.tmp" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name "argus-postgres-*.sql.gz" -size 0 -delete

# Retention.
find "$BACKUP_DIR" -maxdepth 1 -type f -name "argus-postgres-*.sql.gz" -mtime +"$RETENTION_DAYS" -delete

size="$(du -h "$final_file" | awk '{print $1}')"
log "Backup created: $final_file ($size)"
