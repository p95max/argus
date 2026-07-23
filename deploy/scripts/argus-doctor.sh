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
PROBLEMS=()

SERVICES=(
    argus-web.service
    argus-telegram-bot.service
)

TIMERS=(
    argus-check-gmail.timer
    argus-unread-reminders.timer
    argus-cleanup-old-leads.timer
    argus-auto-deploy.timer
    argus-backup-db.timer
    argus-sync-db-to-neon.timer
    argus-health-monitor.timer
)

SCRIPTS=(
    deploy/scripts/argus-backup-db.sh
    deploy/scripts/argus-sync-db-to-neon.sh
    deploy/scripts/argus-health-notify.py
    deploy/scripts/argus-auto-deploy.sh
    deploy/scripts/argus-deploy-notify.py
    deploy/scripts/argus-doctor.sh
    deploy/scripts/argus-run-background-job.sh
)

cleanup() {
    if [[ -n "${HEALTH_BODY:-}" && -f "$HEALTH_BODY" ]]; then
        rm -f "$HEALTH_BODY"
    fi
}
trap cleanup EXIT

read_env_value() {
    local key="$1"
    local line=""
    local value=""

    [[ -f "$ENV_FILE" ]] || return 0
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    printf '%s' "$value"
}

ENV_BASE_URL="$(read_env_value ARGUS_PUBLIC_BASE_URL)"
ENV_HEALTH_TOKEN="$(read_env_value ARGUS_HEALTH_TOKEN)"
[[ -n "$ENV_BASE_URL" ]] && ARGUS_PUBLIC_BASE_URL="${ENV_BASE_URL%/}"
[[ -n "$ENV_HEALTH_TOKEN" ]] && ARGUS_HEALTH_TOKEN="$ENV_HEALTH_TOKEN"

record_problem() {
    PROBLEMS+=("$*")
    EXIT_CODE=1
}

count_active() {
    local count=0
    local unit
    for unit in "$@"; do
        if systemctl is-active --quiet "$unit"; then
            count=$((count + 1))
        else
            record_problem "$unit is not active"
        fi
    done
    printf '%s' "$count"
}

count_enabled() {
    local count=0
    local unit
    for unit in "$@"; do
        if systemctl is-enabled --quiet "$unit"; then
            count=$((count + 1))
        else
            record_problem "$unit is not enabled"
        fi
    done
    printf '%s' "$count"
}

check_deployment() {
    local relative_path
    local deployed_path
    local repo_path
    local ok_count=0

    for relative_path in "${SCRIPTS[@]}"; do
        deployed_path="/usr/local/bin/$(basename "$relative_path")"
        repo_path="$PROJECT_DIR/$relative_path"

        if [[ ! -f "$repo_path" ]]; then
            record_problem "$repo_path is missing"
            continue
        fi
        if [[ ! -x "$deployed_path" ]]; then
            record_problem "$deployed_path is missing or not executable"
            continue
        fi
        if ! cmp -s "$repo_path" "$deployed_path"; then
            record_problem "$deployed_path differs from repository; run deploy/install-ops.sh"
            continue
        fi
        ok_count=$((ok_count + 1))
    done

    printf '%s' "$ok_count"
}

check_application_health() {
    local attempt=1
    local status="000"
    local args=()

    if [[ -n "$ARGUS_HEALTH_TOKEN" ]]; then
        args=(-H "Authorization: Bearer $ARGUS_HEALTH_TOKEN" "$ARGUS_PUBLIC_BASE_URL/health/full/")
    else
        args=("$ARGUS_PUBLIC_BASE_URL/health/")
    fi

    while [[ "$attempt" -le "$HEALTH_RETRIES" ]]; do
        : > "$HEALTH_BODY"
        status="$(curl -sS --max-time "$HEALTH_TIMEOUT_SECONDS" -o "$HEALTH_BODY" -w "%{http_code}" "${args[@]}" || true)"
        if [[ "$status" == "200" ]] && grep -q '"status": "ok"' "$HEALTH_BODY"; then
            return 0
        fi
        [[ "$attempt" -lt "$HEALTH_RETRIES" ]] && sleep "$HEALTH_RETRY_SLEEP_SECONDS"
        attempt=$((attempt + 1))
    done

    record_problem "application health check failed with HTTP $status"
    return 1
}

backup_job_status() {
    local label="$1"
    local timer="$2"
    local service="$3"
    local timer_state
    local result
    local last_run

    timer_state="$(systemctl is-active "$timer" 2>/dev/null || true)"
    result="$(systemctl show "$service" --property=Result --value 2>/dev/null || true)"
    last_run="$(systemctl show "$service" --property=ExecMainExitTimestamp --value 2>/dev/null || true)"
    [[ -n "$last_run" ]] || last_run="not run yet"

    if [[ "$timer_state" != "active" || "$result" != "success" ]]; then
        record_problem "$label backup is unhealthy: timer=$timer_state result=${result:-unknown}"
    fi

    printf '  %s: %s (timer: %s, last run: %s)\n' \
        "$label" "${result:-unknown}" "${timer_state:-unknown}" "$last_run"
}

timer_status() {
    local label="$1"
    local timer="$2"
    local enabled
    local active
    local next_run

    enabled="$(systemctl is-enabled "$timer" 2>/dev/null || true)"
    active="$(systemctl is-active "$timer" 2>/dev/null || true)"
    next_run="$(systemctl show "$timer" --property=NextElapseUSecRealtime --value 2>/dev/null || true)"
    if [[ -z "$next_run" || "$next_run" == "n/a" || "$next_run" == "0" ]]; then
        next_run="$(systemctl list-timers --all --no-legend --no-pager 2>/dev/null | grep -F "$timer" | head -n 1 || true)"
    fi
    [[ -n "$next_run" ]] || next_run="not scheduled"

    printf '  %s: %s (enabled: %s, next run: %s)\n' \
        "$label" "${active:-unknown}" "${enabled:-unknown}" "$next_run"
}

cd "$PROJECT_DIR"
HEALTH_BODY="$(mktemp /tmp/argus-health.XXXXXX.json)"

if [[ ! -x "$GIT_BIN" ]]; then
    record_problem "git binary not found: $GIT_BIN"
elif ! "$GIT_BIN" diff --quiet || ! "$GIT_BIN" diff --cached --quiet; then
    record_problem "git working tree has uncommitted changes"
fi

SERVICES_ACTIVE="$(count_active "${SERVICES[@]}")"
SERVICES_ENABLED="$(count_enabled "${SERVICES[@]}")"
TIMERS_ACTIVE="$(count_active "${TIMERS[@]}")"
TIMERS_ENABLED="$(count_enabled "${TIMERS[@]}")"
DEPLOYED_SCRIPTS="$(check_deployment)"

APPLICATION_STATUS="Healthy"
if ! check_application_health; then
    APPLICATION_STATUS="Unhealthy"
fi

FAILED_UNITS_COUNT="$(systemctl --failed --no-legend | grep -c . || true)"
if [[ "$FAILED_UNITS_COUNT" -gt 0 ]]; then
    record_problem "systemd has $FAILED_UNITS_COUNT failed unit(s)"
fi

DISK_USED_PERCENT="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
if [[ "$DISK_USED_PERCENT" -ge 90 ]]; then
    record_problem "disk usage is high: ${DISK_USED_PERCENT}%"
fi

printf '=== ARGUS HEALTH CHECK ===\n\n'
printf 'Services:       %s (%s/%s active, %s/%s enabled)\n' \
    "$([[ "$SERVICES_ACTIVE" == "${#SERVICES[@]}" && "$SERVICES_ENABLED" == "${#SERVICES[@]}" ]] && echo OK || echo FAILED)" \
    "$SERVICES_ACTIVE" "${#SERVICES[@]}" "$SERVICES_ENABLED" "${#SERVICES[@]}"
printf 'Scheduled jobs: %s (%s/%s active, %s/%s enabled)\n' \
    "$([[ "$TIMERS_ACTIVE" == "${#TIMERS[@]}" && "$TIMERS_ENABLED" == "${#TIMERS[@]}" ]] && echo OK || echo FAILED)" \
    "$TIMERS_ACTIVE" "${#TIMERS[@]}" "$TIMERS_ENABLED" "${#TIMERS[@]}"
printf 'Ops deployment: %s (%s/%s scripts current)\n' \
    "$([[ "$DEPLOYED_SCRIPTS" == "${#SCRIPTS[@]}" ]] && echo OK || echo FAILED)" \
    "$DEPLOYED_SCRIPTS" "${#SCRIPTS[@]}"
printf 'Application:    %s\n' "$APPLICATION_STATUS"
printf 'Server timers:\n'
timer_status "Gmail checks" "argus-check-gmail.timer"
timer_status "Unread reminders" "argus-unread-reminders.timer"
timer_status "Lead cleanup" "argus-cleanup-old-leads.timer"
timer_status "Automatic deploy" "argus-auto-deploy.timer"
timer_status "Local backup" "argus-backup-db.timer"
timer_status "Remote backup" "argus-sync-db-to-neon.timer"
timer_status "Health monitor" "argus-health-monitor.timer"
printf 'Backups:\n'
backup_job_status "Local archive" "argus-backup-db.timer" "argus-backup-db.service"
backup_job_status "Remote copy" "argus-sync-db-to-neon.timer" "argus-sync-db-to-neon.service"
printf 'Systemd:        %s\n' "$([[ "$FAILED_UNITS_COUNT" -eq 0 ]] && echo 'No failed units' || echo "$FAILED_UNITS_COUNT failed unit(s)")"
printf 'Disk usage:     %s%%\n' "$DISK_USED_PERCENT"

if [[ "$EXIT_CODE" -eq 0 ]]; then
    printf '\nOverall status: HEALTHY\n'
else
    printf '\nProblems:\n'
    for problem in "${PROBLEMS[@]}"; do
        printf -- '- %s\n' "$problem"
    done
    printf '\nOverall status: UNHEALTHY\n'
fi

exit "$EXIT_CODE"
