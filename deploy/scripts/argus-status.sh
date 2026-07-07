#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/argus"
ENV_FILE="$PROJECT_DIR/.env.local"
ARGUS_PUBLIC_BASE_URL="http://127.0.0.1:8000"

if [ -f "$ENV_FILE" ]; then
    ENV_BASE_URL="$(grep -E '^ARGUS_PUBLIC_BASE_URL=' "$ENV_FILE" | cut -d '=' -f2- | tr -d "\"'" || true)"
    if [ -n "$ENV_BASE_URL" ]; then
        ARGUS_PUBLIC_BASE_URL="${ENV_BASE_URL%/}"
    fi
fi

echo "=== ARGUS STATUS ==="
date
echo

echo "=== Git ==="
cd "$PROJECT_DIR"
git status --short
git log --oneline -3
echo

echo "=== Health ==="
curl -s "$ARGUS_PUBLIC_BASE_URL/health/" || true
echo
echo

echo "=== Services ==="
{ systemctl --no-pager --full status argus-web || true; } | sed -n '1,12p'
echo
{ systemctl --no-pager --full status argus-telegram-bot || true; } | sed -n '1,12p'
echo

echo "=== Timers ==="
systemctl list-timers --all | grep argus || true
echo

echo "=== Failed units ==="
systemctl --failed || true
echo

echo "=== Disk ==="
df -h /
echo

echo "=== Memory ==="
free -h
echo

echo "=== Recent web logs ==="
journalctl -u argus-web -n 20 --no-pager -l
echo

echo "=== Recent telegram logs ==="
journalctl -u argus-telegram-bot -n 20 --no-pager -l
