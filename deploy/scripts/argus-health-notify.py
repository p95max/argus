#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ENV_FILE = Path("/opt/argus/.env.local")
STATE_FILE = Path("/var/tmp/argus-health-state.json")
HEALTH_URL = "http://45.9.61.214/health/"

SERVICES = [
    "argus-web.service",
    "argus-telegram-bot.service",
]

TIMERS = [
    "argus-check-gmail.timer",
    "argus-unread-reminders.timer",
    "argus-cleanup-old-leads.timer",
    "argus-auto-deploy.timer",
]


def load_env():
    env = {}
    if not ENV_FILE.exists():
        return env

    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def run(command):
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def is_active(unit):
    result = run(["systemctl", "is-active", unit])
    return result.stdout.strip() == "active"


def check_health_url():
    try:
        request = urllib.request.Request(
            HEALTH_URL,
            headers={"User-Agent": "argus-health-monitor"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
            return (
                response.status == 200
                and '"status": "ok"' in body
                or '{"status": "ok"}' in body
            )
    except Exception:
        return False


def get_failed_units():
    result = run(["systemctl", "--failed", "--no-legend"])
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines


def check_disk():
    usage = shutil.disk_usage("/")
    used_percent = round((usage.used / usage.total) * 100, 1)
    return used_percent


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send test Telegram notification")
    args = parser.parse_args()

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_DEFAULT_CHAT_ID", "")

    if not chat_id:
        allowed = env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        chat_id = allowed.split(",")[0].strip() if allowed else ""

    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_DEFAULT_CHAT_ID is missing.")
        return 2

    if args.test:
        send_telegram(
            token,
            chat_id,
            "✅ [DEV] Argus monitor test\nTelegram notifications are working.",
        )
        print("Test notification sent.")
        return 0

    problems = []

    for service in SERVICES:
        if not is_active(service):
            problems.append(f"Service not active: {service}")

    for timer in TIMERS:
        if not is_active(timer):
            problems.append(f"Timer not active: {timer}")

    if not check_health_url():
        problems.append(f"Health check failed: {HEALTH_URL}")

    failed_units = get_failed_units()
    if failed_units:
        problems.append("Failed systemd units:\n" + "\n".join(failed_units[:10]))

    disk_used = check_disk()
    if disk_used >= 90:
        problems.append(f"Disk usage is high: {disk_used}%")

    state = load_state()
    current_status = "fail" if problems else "ok"
    problem_text = "\n".join(problems)
    problem_hash = hashlib.sha256(problem_text.encode("utf-8")).hexdigest() if problems else ""

    previous_status = state.get("status")
    previous_hash = state.get("problem_hash")

    if current_status == "fail":
        if previous_status != "fail" or previous_hash != problem_hash:
            message = (
                "🚨 [DEV] Argus problem detected\n\n"
                + problem_text
                + "\n\n"
                + f"Time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
            send_telegram(token, chat_id, message)
            print("Problem notification sent.")
        else:
            print("Problem still active. Notification already sent.")
    else:
        if previous_status == "fail":
            send_telegram(
                token,
                chat_id,
                "✅ [DEV] Argus recovered\nAll monitored services and checks are OK.",
            )
            print("Recovery notification sent.")
        else:
            print("OK. No problems.")

    save_state(
        {
            "status": current_status,
            "problem_hash": problem_hash,
            "updated_at": int(time.time()),
        }
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
