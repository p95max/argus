#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ENV_FILE = Path("/opt/argus/.env.local")
STATE_FILE = Path("/var/tmp/argus-health-state.json")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

SERVICES = [
    "argus-web.service",
    "argus-telegram-bot.service",
]

TIMERS = [
    "argus-check-gmail.timer",
    "argus-unread-reminders.timer",
    "argus-cleanup-old-leads.timer",
    "argus-auto-deploy.timer",
    "argus-backup-db.timer",
    "argus-health-monitor.timer",
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


def build_url(base_url, path):
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def request_json(url, *, token=""):
    headers = {"User-Agent": "argus-health-monitor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.status, json.loads(body)


def check_health(env):
    base_url = env.get("ARGUS_PUBLIC_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    token = env.get("ARGUS_HEALTH_TOKEN", "")

    if token:
        full_url = build_url(base_url, "/health/full/")
        try:
            status, payload = request_json(full_url, token=token)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return False, f"Full health check failed: {full_url} ({exc})"

        if status != 200 or payload.get("status") != "ok":
            detail = payload.get("status", "unknown")
            checks = payload.get("checks", {})
            failed = [
                f"{name}: {check.get('detail') or check.get('status')}"
                for name, check in checks.items()
                if not check.get("ok")
            ]
            if failed:
                detail = "; ".join(failed)
            return False, f"Full health degraded: {detail}"
        return True, f"Full health OK: {full_url}"

    simple_url = build_url(base_url, "/health/")
    try:
        status, payload = request_json(simple_url)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return False, f"Health check failed: {simple_url} ({exc})"

    if status != 200 or payload.get("status") != "ok":
        return False, f"Health check failed: {simple_url}"
    return True, f"Health OK: {simple_url}"


def get_failed_units():
    result = run(["systemctl", "--failed", "--no-legend"])
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines


def check_disk():
    usage = shutil.disk_usage("/")
    return round((usage.used / usage.total) * 100, 1)


def build_problem_message(label, problem_text):
    return (
        f"🔴 [{label}] Argus problem detected\n"
        "LED: 🔴 CRITICAL\n"
        "Status: FAIL\n\n"
        "Problems:\n"
        f"{format_problem_list(problem_text)}\n\n"
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )


def build_recovery_message(label):
    return (
        f"🟢 [{label}] Argus recovered\n"
        "LED: 🟢 OK\n"
        "Status: RECOVERED\n\n"
        "All monitored services and checks are OK."
    )


def build_test_message(label):
    return (
        f"🟢 [{label}] Argus monitor test\n"
        "LED: 🟢 OK\n"
        "Status: TEST\n\n"
        "Telegram notifications are working."
    )


def format_problem_list(problem_text):
    lines = [line.rstrip() for line in str(problem_text or "").splitlines()]
    if not lines:
        return "• Unknown problem"

    formatted = []
    for line in lines:
        if not line.strip():
            continue
        if line.startswith((" ", "\t", "●")):
            formatted.append(f"  {line.strip()}")
        else:
            formatted.append(f"• {line.strip()}")
    return "\n".join(formatted) or "• Unknown problem"


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


def try_send_telegram(token, chat_id, text):
    try:
        send_telegram(token, chat_id, text)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Telegram API returned HTTP {exc.code}.")
        return False
    except urllib.error.URLError as exc:
        print(f"ERROR: Telegram request failed: {exc.reason}")
        return False
    except TimeoutError:
        print("ERROR: Telegram request timed out.")
        return False
    except OSError as exc:
        print(f"ERROR: Telegram notification failed: {exc.__class__.__name__}")
        return False
    return True


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def first_chat_id(env):
    chat_id = env.get("TELEGRAM_DEFAULT_CHAT_ID", "")
    if chat_id:
        return chat_id
    allowed = env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
    return allowed.split(",")[0].strip() if allowed else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send test Telegram notification")
    args = parser.parse_args()

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = first_chat_id(env)
    label = env.get("ARGUS_ENV_LABEL", "PROD")

    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_DEFAULT_CHAT_ID is missing.")
        return 2

    if args.test:
        if try_send_telegram(token, chat_id, build_test_message(label)):
            print("Test notification sent.")
            return 0
        return 1

    problems = []

    for service in SERVICES:
        if not is_active(service):
            problems.append(f"Service not active: {service}")

    for timer in TIMERS:
        if not is_active(timer):
            problems.append(f"Timer not active: {timer}")

    health_ok, health_detail = check_health(env)
    if not health_ok:
        problems.append(health_detail)

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
    notification_failed = False

    if current_status == "fail":
        if previous_status != "fail" or previous_hash != problem_hash:
            if try_send_telegram(token, chat_id, build_problem_message(label, problem_text)):
                print("Problem notification sent.")
            else:
                notification_failed = True
        else:
            print("Problem still active. Notification already sent.")
    else:
        if previous_status == "fail":
            if try_send_telegram(token, chat_id, build_recovery_message(label)):
                print("Recovery notification sent.")
            else:
                notification_failed = True
        else:
            print("OK. No problems.")

    if notification_failed:
        print("State not updated because Telegram notification failed; next run will retry.")
        return 1

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
