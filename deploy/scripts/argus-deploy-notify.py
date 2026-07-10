#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_DIR = Path("/opt/argus")
ENV_FILE = PROJECT_DIR / ".env.local"
PENDING_REQUEST_FILE = Path("/var/tmp/argus-telegram-deploy-request.json")
ACTIVE_REQUEST_FILE = Path("/var/tmp/argus-telegram-deploy-active.json")
DEPLOY_RESULTS = ("success", "updated", "up_to_date")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env

    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    if not token or not chat_id:
        print("Deploy notify: Telegram token or chat ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        print(f"Deploy notify: Telegram API returned HTTP {exc.code}.")
        return False
    except urllib.error.URLError as exc:
        print(f"Deploy notify: Telegram request failed: {exc.reason}")
        return False
    except (TimeoutError, OSError) as exc:
        print(f"Deploy notify: Telegram notification failed: {exc.__class__.__name__}")
        return False

    return True


def format_time(timestamp: float | int | None) -> str:
    if not timestamp:
        return "unknown"
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(float(timestamp)))


def current_head() -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(PROJECT_DIR), "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def handle_start() -> int:
    if not PENDING_REQUEST_FILE.exists():
        return 0

    try:
        PENDING_REQUEST_FILE.replace(ACTIVE_REQUEST_FILE)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        print(f"Deploy notify: could not claim pending request: {exc}")
        return 0

    request = load_json(ACTIVE_REQUEST_FILE)
    started_at = time.time()
    request["started_at"] = started_at
    try:
        write_json(ACTIVE_REQUEST_FILE, request)
    except OSError as exc:
        print(f"Deploy notify: could not update active request: {exc}")

    requested_at = request.get("requested_at")
    try:
        waited_seconds = max(0, int(started_at - float(requested_at)))
    except (TypeError, ValueError):
        waited_seconds = 0

    env = load_env()
    label = env.get("ARGUS_ENV_LABEL", "PROD")
    text = (
        f"🚀 [{label}] Argus deploy started\n"
        f"Requested: {format_time(requested_at)}\n"
        f"Started: {format_time(started_at)}\n"
        f"Queue wait: {waited_seconds}s"
    )
    send_telegram(
        env.get("TELEGRAM_BOT_TOKEN", ""),
        str(request.get("chat_id", "")),
        text,
    )
    return 0


def handle_finish(status: int, result: str = "success") -> int:
    if not ACTIVE_REQUEST_FILE.exists():
        return 0

    request = load_json(ACTIVE_REQUEST_FILE)
    finished_at = time.time()
    started_at = request.get("started_at")
    try:
        duration_seconds = max(0, int(finished_at - float(started_at)))
    except (TypeError, ValueError):
        duration_seconds = 0

    env = load_env()
    label = env.get("ARGUS_ENV_LABEL", "PROD")
    if status == 0 and result == "up_to_date":
        text = (
            f"✅ [{label}] Argus deploy check finished\n"
            "Status: UP TO DATE\n"
            f"HEAD: {current_head()}\n"
            "No new commit was available; services were not redeployed.\n"
            f"Duration: {duration_seconds}s\n"
            f"Finished: {format_time(finished_at)}"
        )
    elif status == 0:
        result_label = "UPDATED" if result == "updated" else "SUCCESS"
        text = (
            f"✅ [{label}] Argus deploy finished\n"
            f"Status: {result_label}\n"
            f"HEAD: {current_head()}\n"
            f"Duration: {duration_seconds}s\n"
            f"Finished: {format_time(finished_at)}"
        )
    else:
        text = (
            f"🚨 [{label}] Argus deploy failed\n"
            f"Exit status: {status}\n"
            f"Duration: {duration_seconds}s\n"
            f"Finished: {format_time(finished_at)}\n"
            "Run /doctor and inspect argus-auto-deploy.service logs."
        )

    send_telegram(
        env.get("TELEGRAM_BOT_TOKEN", ""),
        str(request.get("chat_id", "")),
        text,
    )
    ACTIVE_REQUEST_FILE.unlink(missing_ok=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="event", required=True)
    subparsers.add_parser("start")
    finish_parser = subparsers.add_parser("finish")
    finish_parser.add_argument("--status", type=int, required=True)
    finish_parser.add_argument(
        "--result",
        choices=DEPLOY_RESULTS,
        default="success",
    )
    args = parser.parse_args()

    if args.event == "start":
        return handle_start()
    return handle_finish(args.status, args.result)


if __name__ == "__main__":
    raise SystemExit(main())
