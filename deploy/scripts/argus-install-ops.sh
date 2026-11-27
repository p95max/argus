#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
SYSTEMD_DIR="/etc/systemd/system"
BIN_DIR="/usr/local/bin"
SUDOERS_DIR="/etc/sudoers.d"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: argus-install-ops.sh must run as root." >&2
    exit 1
fi

cd "$PROJECT_DIR"

for required in deploy/systemd deploy/scripts deploy/sudoers; do
    [[ -d "$required" ]] || {
        echo "ERROR: missing $required" >&2
        exit 1
    }
done

# Validate sudoers before replacing the active policy.
tmp_sudoers="$(mktemp /tmp/argus-sudoers.XXXXXX)"
trap 'rm -f "$tmp_sudoers"' EXIT
install -m 0440 deploy/sudoers/argus-auto-deploy "$tmp_sudoers"
visudo -cf "$tmp_sudoers" >/dev/null

# Install only the known Argus operational surfaces.
install -m 0644 deploy/systemd/argus-*.service deploy/systemd/argus-*.timer "$SYSTEMD_DIR/"
install -o root -g argus -m 0750 deploy/scripts/argus-* "$BIN_DIR/"
install -o root -g root -m 0440 "$tmp_sudoers" "$SUDOERS_DIR/argus-auto-deploy"
visudo -cf "$SUDOERS_DIR/argus-auto-deploy" >/dev/null

systemctl daemon-reload

systemctl enable     argus-web.service     argus-telegram-bot.service     argus-check-gmail.timer     argus-unread-reminders.timer     argus-cleanup-old-leads.timer     argus-auto-deploy.timer     argus-backup-db.timer     argus-sync-db-to-neon.timer     argus-health-monitor.timer

systemctl restart argus-web.service argus-telegram-bot.service

# Restart timers so changed schedules are applied immediately. Do not start
# oneshot job services here: timers will run them on their normal schedule.
systemctl restart     argus-check-gmail.timer     argus-unread-reminders.timer     argus-cleanup-old-leads.timer     argus-auto-deploy.timer     argus-backup-db.timer     argus-sync-db-to-neon.timer     argus-health-monitor.timer

# Clear stale failed states from completed oneshot jobs after the new
# operational layer is installed. Real failures will reappear on the next run.
systemctl reset-failed     argus-check-gmail.service     argus-unread-reminders.service     argus-cleanup-old-leads.service     argus-auto-deploy.service     argus-backup-db.service     argus-sync-db-to-neon.service     argus-health-monitor.service     2>/dev/null || true

echo "Argus ops layer synchronized and services/timers restarted."
