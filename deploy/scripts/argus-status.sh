#!/usr/bin/env bash
set -euo pipefail

echo "=== ARGUS STATUS ==="
date
echo

echo "=== Git ==="
cd /opt/argus
git status --short
git log --oneline -3
echo

echo "=== Health ==="
curl -s http://45.9.61.214/health/ || true
echo
echo

echo "=== Services ==="
systemctl --no-pager --full status argus-web | sed -n '1,12p'
echo
systemctl --no-pager --full status argus-telegram-bot | sed -n '1,12p'
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
