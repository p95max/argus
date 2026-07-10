import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone

from .handlers import PERMISSION_DENIED_MESSAGE
from .i18n import telegram_gettext
from .permissions import is_allowed_update


logger = logging.getLogger(__name__)

DEPLOY_SERVICE = "argus-auto-deploy.service"
PENDING_REQUEST_FILE = Path("/var/tmp/argus-telegram-deploy-request.json")
ACTIVE_REQUEST_FILE = Path("/var/tmp/argus-telegram-deploy-active.json")
QUEUE_LOCK_FILE = Path("/tmp/argus-background-jobs.lock")
SYSTEMCTL_BIN = "/usr/bin/systemctl"
SUDO_BIN = "/usr/bin/sudo"
FLOCK_BIN = "/usr/bin/flock"
TRUE_BIN = "/bin/true"


@dataclass(frozen=True)
class DeployQueueResult:
    ok: bool
    message: str


def _service_state() -> str:
    try:
        result = subprocess.run(
            [SYSTEMCTL_BIN, "show", DEPLOY_SERVICE, "--property=ActiveState", "--value"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"

    return result.stdout.strip() or "unknown"


def _queue_is_busy() -> bool:
    try:
        result = subprocess.run(
            [FLOCK_BIN, "-n", str(QUEUE_LOCK_FILE), TRUE_BIN],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return True

    return result.returncode != 0


def _write_pending_request(chat_id: str, user_id: str) -> bool:
    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "requested_at": timezone.now().timestamp(),
        "requested_at_iso": timezone.localtime().isoformat(timespec="seconds"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")

    try:
        fd = os.open(
            PENDING_REQUEST_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return False

    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        PENDING_REQUEST_FILE.unlink(missing_ok=True)
        raise

    return True


def request_deploy(chat_id: str, user_id: str = "") -> DeployQueueResult:
    service_state = _service_state()
    if service_state in {"active", "activating", "reloading"}:
        return DeployQueueResult(
            ok=True,
            message=(
                "⏳ <b>Argus deploy</b>\n"
                "Деплой уже выполняется или ожидает общую очередь. "
                "После завершения придёт отдельное сообщение."
            ),
        )

    if ACTIVE_REQUEST_FILE.exists():
        return DeployQueueResult(
            ok=True,
            message=(
                "⏳ <b>Argus deploy</b>\n"
                "Telegram-запрос на деплой уже обрабатывается. "
                "После завершения придёт отдельное сообщение."
            ),
        )

    queue_busy = _queue_is_busy()

    try:
        created = _write_pending_request(chat_id=chat_id, user_id=user_id)
    except OSError as exc:
        logger.exception("Could not create Telegram deploy request file.")
        return DeployQueueResult(
            ok=False,
            message=(
                "🚨 <b>Argus deploy</b>\n"
                f"Не удалось создать запрос: {exc.__class__.__name__}."
            ),
        )

    if not created:
        return DeployQueueResult(
            ok=True,
            message=(
                "⏳ <b>Argus deploy</b>\n"
                "Запрос уже поставлен в очередь. "
                "После завершения придёт отдельное сообщение."
            ),
        )

    try:
        result = subprocess.run(
            [
                SUDO_BIN,
                "-n",
                SYSTEMCTL_BIN,
                "start",
                "--no-block",
                DEPLOY_SERVICE,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        PENDING_REQUEST_FILE.unlink(missing_ok=True)
        logger.exception("Could not enqueue Telegram deploy request.")
        return DeployQueueResult(
            ok=False,
            message=(
                "🚨 <b>Argus deploy</b>\n"
                f"Не удалось поставить деплой в очередь: {exc.__class__.__name__}."
            ),
        )

    if result.returncode != 0:
        PENDING_REQUEST_FILE.unlink(missing_ok=True)
        detail = (result.stdout or "systemctl start failed").strip()
        logger.error("Telegram deploy enqueue failed: %s", detail)
        return DeployQueueResult(
            ok=False,
            message=(
                "🚨 <b>Argus deploy</b>\n"
                "Не удалось поставить деплой в очередь.\n"
                f"<pre>{detail[:1200]}</pre>"
            ),
        )

    if queue_busy:
        timing = (
            "Общая очередь занята: запуск произойдёт после текущей задачи. "
            "Максимальное ожидание — 15 минут."
        )
    else:
        timing = "Общая очередь свободна: запуск ожидается сейчас."

    return DeployQueueResult(
        ok=True,
        message=(
            "🚀 <b>Argus deploy</b>\n"
            "Статус: поставлен в общую очередь.\n"
            f"{timing}\n\n"
            "Бот отдельно сообщит о фактическом старте и результате."
        ),
    )


async def handle_deploy_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info(
        "Telegram deploy command received. chat_id=%s user_id=%s",
        chat_id,
        user_id,
    )

    if not is_allowed_update(update):
        logger.warning(
            "Telegram deploy command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            telegram_gettext(PERMISSION_DENIED_MESSAGE),
        )
        return

    result = await sync_to_async(request_deploy, thread_sensitive=False)(
        chat_id=chat_id,
        user_id=user_id,
    )

    await update.effective_message.reply_text(
        result.message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info(
        "Telegram deploy command handled. chat_id=%s user_id=%s ok=%s",
        chat_id,
        user_id,
        result.ok,
    )
