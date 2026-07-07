#!/bin/bash
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

PROJECT_DIR="/opt/argus"
ENV_FILE="$PROJECT_DIR/.env.local"
ARGUS_PUBLIC_BASE_URL="http://127.0.0.1:8000"
ARGUS_HEALTH_TOKEN=""
EXIT_CODE=0

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

check_timer() {
    local unit="$1"
    if systemctl is-active --quiet "$unit"; then
        ok "$unit active"
    else
        fail "$unit is not active"
    fi
}

cd "$PROJECT_DIR"

echo "=== ARGUS DOCTOR ==="
date
echo

if git diff --quiet && git diff --cached --quiet; then
    ok "git working tree clean"
else
    fail "git working tree has uncommitted changes"
    git status --short
fi

check_active argus-web.service
check_active argus-telegram-bot.service

check_timer argus-check-gmail.timer
check_timer argus-unread-reminders.timer
check_timer argus-cleanup-old-leads.timer
check_timer argus-auto-deploy.timer
check_timer argus-backup-db.timer
check_timer argus-health-monitor.timer

if [ -n "$ARGUS_HEALTH_TOKEN" ]; then
    HEALTH_STATUS="$(curl -sS -o /tmp/argus-health-full.json -w "%{http_code}" -H "Authorization: Bearer $ARGUS_HEALTH_TOKEN" "$ARGUS_PUBLIC_BASE_URL/health/full/" || true)"
    if [ "$HEALTH_STATUS" = "200" ] && grep -q '"status": "ok"' /tmp/argus-health-full.json; then
        ok "full health OK"
    else
        fail "full health failed with HTTP $HEALTH_STATUS"
        cat /tmp/argus-health-full.json || true
    fi
else
    HEALTH_STATUS="$(curl -sS -o /tmp/argus-health.json -w "%{http_code}" "$ARGUS_PUBLIC_BASE_URL/health/" || true)"
    if [ "$HEALTH_STATUS" = "200" ] && grep -q '"status": "ok"' /tmp/argus-health.json; then
        ok "health OK"
    else
        fail "health failed with HTTP $HEALTH_STATUS"
        cat /tmp/argus-health.json || true
    fi
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
