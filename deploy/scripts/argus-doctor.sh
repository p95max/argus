#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.local}"
ARGUS_PUBLIC_BASE_URL="http://127.0.0.1:8000"
ARGUS_HEALTH_TOKEN=""
GIT_BIN="${GIT_BIN:-/usr/bin/git}"
HEALTH_RETRIES="${HEALTH_RETRIES:-5}"
HEALTH_RETRY_SLEEP_SECONDS="${HEALTH_RETRY_SLEEP_SECONDS:-2}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-8}"
EXIT_CODE=0
HEALTH_BODY=""

cleanup() {
    if [ -n "${HEALTH_BODY:-}" ] && [ -f "$HEALTH_BODY" ]; then
        rm -f "$HEALTH_BODY"
    fi
}
trap cleanup EXIT

if [ -f "$ENV_FILE" ]; then
    ENV_BASE_URL="$(grep -E '^ARGUS_PUBLIC_BASE_URL=' "$ENV_FILE" | cut -d '=' -f2- | tr -d "\"'" || true)"
    ENV_HEALTH_TOKEN="$(grep -E '^ARGUS_HEALTH_TOKEN=' "$ENV_FILE" | cut -d '=' -f2- | tr -d "\"'" || true)"
    if [ -n "$ENV_BASE_URL" ]; then
        ARGUS_PUBLIC_BASE_URL="${ENV_BASE_URL%/}"
    fi
    if [ -n "$ENV_HEALTH_TOKEN" ]; then
        ARGUS_HEALTH_TOKEN="$ENV_HEALTH_TOKEN"
    fi
fi

fail() {
    echo "FAIL: $*"
    EXIT_CODE=1
}

ok() {
    echo "OK: $*"
}

check_active() {
    local unit="$1"
    if systemctl is-active --quiet "$unit"; then
        ok "$unit active"
    else
        fail "$unit is not active"
    fi
}

check_enabled() {
    local unit="$1"
    if systemctl is-enabled --quiet "$unit"; then
        ok "$unit enabled"
    else
        fail "$unit is not enabled"
    fi
}

check_executable() {
    local path="$1"
    if [ -x "$path" ]; then
        ok "$path executable"
    else
        fail "$path is missing or not executable"
    fi
}

check_deployed_copy() {
    local relative_path="$1"
    local deployed_path="/usr/local/bin/$(basename "$relative_path")"
    local repo_path="$PROJECT_DIR/$relative_path"

    if [ ! -f "$repo_path" ]; then
        fail "$repo_path missing in repository"
        return
    fi

    if [ ! -f "$deployed_path" ]; then
        fail "$deployed_path missing"
        return
    fi

    if cmp -s "$repo_path" "$deployed_path"; then
        ok "$deployed_path matches repository"
    else
        fail "$deployed_path differs from $repo_path; run deploy/install-ops.sh"
    fi
}

check_health_url() {
    local label="$1"
    local body_file="$2"
    shift 2

    local attempt=1
    local status="000"

    while [ "$attempt" -le "$HEALTH_RETRIES" ]; do
        : > "$body_file"
        status="$(curl -sS --max-time "$HEALTH_TIMEOUT_SECONDS" -o "$body_file" -w "%{http_code}" "$@" || true)"

        if [ "$status" = "200" ] && grep -q '"status": "ok"' "$body_file"; then
            if [ "$attempt" -eq 1 ]; then
                ok "$label OK"
            else
                ok "$label OK after $attempt attempts"
            fi
            return 0
        fi

        if [ "$attempt" -lt "$HEALTH_RETRIES" ]; then
            sleep "$HEALTH_RETRY_SLEEP_SECONDS"
        fi
        attempt=$((attempt + 1))
    done

    fail "$label failed with HTTP $status after $HEALTH_RETRIES attempts"
    cat "$body_file" || true
    return 1
}

cd "$PROJECT_DIR"

HEALTH_BODY="$(mktemp /tmp/argus-health.XXXXXX.json)"

echo "=== ARGUS DOCTOR ==="
date
echo

if [ ! -x "$GIT_BIN" ]; then
    fail "git binary not found: $GIT_BIN"
elif "$GIT_BIN" diff --quiet && "$GIT_BIN" diff --cached --quiet; then
    ok "git working tree clean"
else
    fail "git working tree has uncommitted changes"
    "$GIT_BIN" status --short
fi

check_active argus-web.service
check_active argus-telegram-bot.service

check_enabled argus-web.service
check_enabled argus-telegram-bot.service
check_enabled argus-check-gmail.timer
check_enabled argus-unread-reminders.timer
check_enabled argus-cleanup-old-leads.timer
check_enabled argus-auto-deploy.timer
check_enabled argus-backup-db.timer
check_enabled argus-health-monitor.timer

check_active argus-check-gmail.timer
check_active argus-unread-reminders.timer
check_active argus-cleanup-old-leads.timer
check_active argus-auto-deploy.timer
check_active argus-backup-db.timer
check_active argus-health-monitor.timer

check_executable /usr/local/bin/argus-backup-db.sh
check_executable /usr/local/bin/argus-health-notify.py
check_executable /usr/local/bin/argus-auto-deploy.sh
check_executable /usr/local/bin/argus-doctor.sh

check_deployed_copy deploy/scripts/argus-backup-db.sh
check_deployed_copy deploy/scripts/argus-health-notify.py
check_deployed_copy deploy/scripts/argus-auto-deploy.sh
check_deployed_copy deploy/scripts/argus-doctor.sh

if [ -n "$ARGUS_HEALTH_TOKEN" ]; then
    check_health_url \
        "full health" \
        "$HEALTH_BODY" \
        -H "Authorization: Bearer $ARGUS_HEALTH_TOKEN" \
        "$ARGUS_PUBLIC_BASE_URL/health/full/"
else
    check_health_url \
        "health" \
        "$HEALTH_BODY" \
        "$ARGUS_PUBLIC_BASE_URL/health/"
fi

if systemctl --failed --no-legend | grep -q .; then
    fail "systemd has failed units"
    systemctl --failed
else
    ok "no failed systemd units"
fi

DISK_USED_PERCENT="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
if [ "$DISK_USED_PERCENT" -ge 90 ]; then
    fail "disk usage is high: ${DISK_USED_PERCENT}%"
else
    ok "disk usage ${DISK_USED_PERCENT}%"
fi

echo
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "ARGUS DOCTOR: OK"
else
    echo "ARGUS DOCTOR: FAILED"
fi

exit "$EXIT_CODE"
