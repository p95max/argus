#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
SYSTEMD_DIR="/etc/systemd/system"
BIN_DIR="/usr/local/bin"
SUDOERS_DIR="/etc/sudoers.d"

cd "$PROJECT_DIR"

if [ ! -d deploy/systemd ]; then
    echo "ERROR: deploy/systemd not found. Pull the latest repository version first."
    exit 1
fi

if [ ! -d deploy/scripts ]; then
    echo "ERROR: deploy/scripts not found. Pull the latest repository version first."
    exit 1
fi

if [ ! -d deploy/sudoers ]; then
    echo "ERROR: deploy/sudoers not found. Pull the latest repository version first."
    exit 1
fi

sudo install -m 0644 deploy/systemd/argus-*.service deploy/systemd/argus-*.timer "$SYSTEMD_DIR/"
sudo install -o root -g argus -m 0750 deploy/scripts/argus-* "$BIN_DIR/"
sudo install -o root -g root -m 0440 deploy/sudoers/argus-auto-deploy "$SUDOERS_DIR/argus-auto-deploy"
sudo visudo -cf "$SUDOERS_DIR/argus-auto-deploy"

sudo systemctl daemon-reload

sudo systemctl enable --now \
    argus-web.service \
    argus-telegram-bot.service

sudo systemctl enable --now \
    argus-check-gmail.timer \
    argus-unread-reminders.timer \
    argus-cleanup-old-leads.timer \
    argus-auto-deploy.timer \
    argus-backup-db.timer \
    argus-sync-db-to-neon.timer \
    argus-health-monitor.timer

systemctl status argus-web.service --no-pager -l
systemctl status argus-telegram-bot.service --no-pager -l
systemctl list-timers --all | grep argus

echo
echo "Installed Argus ops scripts, sudoers policy, services, and timers."
echo "Run: /usr/local/bin/argus-doctor.sh"
