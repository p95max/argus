#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
SYSTEMD_DIR="/etc/systemd/system"
BIN_DIR="/usr/local/bin"

cd "$PROJECT_DIR"

if [ ! -d deploy/systemd ]; then
    echo "ERROR: deploy/systemd not found. Pull the latest repository version first."
    exit 1
fi

if [ ! -d deploy/scripts ]; then
    echo "ERROR: deploy/scripts not found. Pull the latest repository version first."
    exit 1
fi

sudo cp deploy/systemd/argus-*.service deploy/systemd/argus-*.timer "$SYSTEMD_DIR/"
sudo cp deploy/scripts/argus-* "$BIN_DIR/"
sudo chmod +x "$BIN_DIR"/argus-*

sudo systemctl daemon-reload
sudo systemctl enable --now \
    argus-check-gmail.timer \
    argus-unread-reminders.timer \
    argus-cleanup-old-leads.timer \
    argus-auto-deploy.timer \
    argus-backup-db.timer \
    argus-health-monitor.timer

systemctl list-timers --all | grep argus

echo
echo "Installed Argus ops scripts and timers."
echo "Run: sudo /usr/local/bin/argus-doctor.sh"
