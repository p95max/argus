#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.local}"
WORK_DIR="${WORK_DIR:-$PROJECT_DIR/backups/neon-sync}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*"
}

fail() {
    log "ERROR: $*" >&2
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

[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"

DATABASE_URL="${DATABASE_URL:-$(read_env_value "DATABASE_URL" "$ENV_FILE")}"
NEON_BACKUP_DATABASE_URL="${NEON_BACKUP_DATABASE_URL:-$(read_env_value "NEON_BACKUP_DATABASE_URL" "$ENV_FILE")}"

[[ -n "$DATABASE_URL" ]] || fail "DATABASE_URL is not configured"
[[ -n "$NEON_BACKUP_DATABASE_URL" ]] || fail "NEON_BACKUP_DATABASE_URL is not configured"
[[ "$DATABASE_URL" != "$NEON_BACKUP_DATABASE_URL" ]] || fail "source and backup database URLs must differ"

PG_DUMP="${PG_DUMP:-}"
PG_RESTORE="${PG_RESTORE:-}"
PSQL="${PSQL:-}"

if [[ -z "$PG_DUMP" ]]; then
    if [[ -x "/usr/lib/postgresql/18/bin/pg_dump" ]]; then
        PG_DUMP="/usr/lib/postgresql/18/bin/pg_dump"
    else
        PG_DUMP="$(command -v pg_dump || true)"
    fi
fi

if [[ -z "$PG_RESTORE" ]]; then
    if [[ -x "/usr/lib/postgresql/18/bin/pg_restore" ]]; then
        PG_RESTORE="/usr/lib/postgresql/18/bin/pg_restore"
    else
        PG_RESTORE="$(command -v pg_restore || true)"
    fi
fi

if [[ -z "$PSQL" ]]; then
    if [[ -x "/usr/lib/postgresql/18/bin/psql" ]]; then
        PSQL="/usr/lib/postgresql/18/bin/psql"
    else
        PSQL="$(command -v psql || true)"
    fi
fi

[[ -n "$PG_DUMP" && -x "$PG_DUMP" ]] || fail "pg_dump not found"
[[ -n "$PG_RESTORE" && -x "$PG_RESTORE" ]] || fail "pg_restore not found"
[[ -n "$PSQL" && -x "$PSQL" ]] || fail "psql not found"

install -d -m 700 "$WORK_DIR"
DUMP_FILE="$(mktemp "$WORK_DIR/.argus-neon-sync.XXXXXX.dump.tmp")"

cleanup() {
    rm -f "${DUMP_FILE:-}"
}
trap cleanup EXIT

log "Creating a consistent dump of the active database"
"$PG_DUMP" \
    --dbname="$DATABASE_URL" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --file="$DUMP_FILE"

[[ -s "$DUMP_FILE" ]] || fail "database dump is empty"
"$PG_RESTORE" --list "$DUMP_FILE" >/dev/null

log "Replacing the Neon backup database in one transaction"
"$PG_RESTORE" \
    --dbname="$NEON_BACKUP_DATABASE_URL" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    --single-transaction \
    --exit-on-error \
    "$DUMP_FILE"

SOURCE_MIGRATIONS="$($PSQL "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -tAc "SELECT COUNT(*) FROM django_migrations;")"
BACKUP_MIGRATIONS="$($PSQL "$NEON_BACKUP_DATABASE_URL" -X -v ON_ERROR_STOP=1 -tAc "SELECT COUNT(*) FROM django_migrations;")"

[[ "$SOURCE_MIGRATIONS" = "$BACKUP_MIGRATIONS" ]] || \
    fail "migration count mismatch: source=$SOURCE_MIGRATIONS backup=$BACKUP_MIGRATIONS"

log "Neon backup synchronized successfully (django_migrations=$BACKUP_MIGRATIONS)"
