#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"
GIT_BIN="${GIT_BIN:-/usr/bin/git}"
RUN_DOCTOR="${RUN_DOCTOR:-1}"
RESTART_SERVICES="${RESTART_SERVICES:-argus-web.service argus-telegram-bot.service}"
AUTO_INSTALL_OPS="${AUTO_INSTALL_OPS:-0}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

run_systemctl() {
    if [ "$(id -u)" -eq 0 ]; then
        systemctl "$@"
    else
        sudo -n systemctl "$@"
    fi
}

cd "$PROJECT_DIR"

[ -x "$GIT_BIN" ] || fail "git binary not found: $GIT_BIN"
[ -x "$PYTHON_BIN" ] || fail "project Python not found or not executable: $PYTHON_BIN"

if [ -z "$DEPLOY_BRANCH" ]; then
    DEPLOY_BRANCH="$($GIT_BIN rev-parse --abbrev-ref HEAD)"
fi

[ -n "$DEPLOY_BRANCH" ] || fail "DEPLOY_BRANCH is empty"
[ "$DEPLOY_BRANCH" != "HEAD" ] || fail "repository is in detached HEAD; set DEPLOY_BRANCH explicitly"

if ! "$GIT_BIN" diff --quiet || ! "$GIT_BIN" diff --cached --quiet; then
    "$GIT_BIN" status --short
    fail "working tree is dirty; refusing to auto-deploy"
fi

old_rev="$($GIT_BIN rev-parse HEAD)"
log "Checking $REMOTE_NAME/$DEPLOY_BRANCH for updates from $old_rev"

"$GIT_BIN" fetch --prune "$REMOTE_NAME" "$DEPLOY_BRANCH"
new_rev="$($GIT_BIN rev-parse "$REMOTE_NAME/$DEPLOY_BRANCH")"

if [ "$old_rev" = "$new_rev" ]; then
    log "Already up to date: $new_rev"
    exit 0
fi

changed_files="$($GIT_BIN diff --name-only "$old_rev" "$new_rev")"
ops_changed=0
if printf '%s\n' "$changed_files" | grep -Eq '^(deploy/systemd/|deploy/scripts/|deploy/sudoers/|deploy/install-ops\.sh$)'; then
    ops_changed=1
fi

log "Deploying $new_rev"

"$GIT_BIN" reset --hard "$REMOTE_NAME/$DEPLOY_BRANCH"

if [ "$ops_changed" = "1" ]; then
    if [ "$AUTO_INSTALL_OPS" = "1" ]; then
        log "Operational files changed; reinstalling systemd units, sudoers policy, and helper scripts"
        bash deploy/install-ops.sh
    else
        log "Operational files changed; manual install required: bash deploy/install-ops.sh"
    fi
fi

if printf '%s\n' "$changed_files" | grep -Eq '^(pyproject\.toml|poetry\.lock)$'; then
    command -v poetry >/dev/null 2>&1 || fail "dependencies changed but poetry is not installed"
    log "Dependencies changed; running poetry install"
    poetry install --no-interaction --only main
fi

log "Running database migrations"
"$PYTHON_BIN" manage.py migrate --noinput

log "Collecting static files"
"$PYTHON_BIN" manage.py collectstatic --noinput

log "Running Django deploy checks"
"$PYTHON_BIN" manage.py check --deploy --fail-level ERROR

log "Running Argus deploy readiness checks"
"$PYTHON_BIN" manage.py argus_check_deploy

log "Restarting services: $RESTART_SERVICES"
# shellcheck disable=SC2086
run_systemctl restart $RESTART_SERVICES

if [ "$RUN_DOCTOR" = "1" ]; then
    if [ "$ops_changed" = "1" ] && [ "$AUTO_INSTALL_OPS" != "1" ]; then
        log "Skipping full doctor because operational files changed and were not auto-installed"
    else
        log "Running Argus doctor"
        bash deploy/scripts/argus-doctor.sh
    fi
fi

log "Auto deploy completed: $old_rev -> $new_rev"
