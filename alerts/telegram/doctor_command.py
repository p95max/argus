import html
import os
import subprocess

from asgiref.sync import sync_to_async

from .git_status import build_git_deploy_status_text
from .i18n import telegram_gettext
from .permissions import is_allowed_update


PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."
DOCTOR_SCRIPT = "/usr/local/bin/argus-doctor.sh"
DOCTOR_TIMEOUT_SECONDS = 25
DOCTOR_OUTPUT_LIMIT = 3300


def get_environment_label() -> str:
    label = os.getenv("ARGUS_ENV_LABEL", "PROD").strip().upper()
    return label or "PROD"


def build_doctor_script_message() -> str:
    label = html.escape(get_environment_label())
    title = f"[{label}] Argus Health Check"

    try:
        result = subprocess.run(
            ["/bin/bash", DOCTOR_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=DOCTOR_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return f"🚨 <b>{title}</b>\n<pre>{DOCTOR_SCRIPT} not found</pre>"
    except subprocess.TimeoutExpired:
        return (
            f"🚨 <b>{title}</b>\n"
            f"<pre>Health check timed out after {DOCTOR_TIMEOUT_SECONDS} seconds.</pre>"
        )

    output = result.stdout.strip() or "(no output)"
    git_output = build_git_deploy_status_text()
    combined_output = f"{output}\n\n{git_output}" if git_output else output

    if len(combined_output) > DOCTOR_OUTPUT_LIMIT:
        combined_output = "... truncated ...\n" + combined_output[-DOCTOR_OUTPUT_LIMIT:]

    icon = "✅" if result.returncode == 0 else "🚨"
    return f"{icon} <b>{title}</b>\n<pre>{html.escape(combined_output)}</pre>"


async def handle_doctor_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(
            telegram_gettext(PERMISSION_DENIED_MESSAGE),
        )
        return

    text = await sync_to_async(build_doctor_script_message)()
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
