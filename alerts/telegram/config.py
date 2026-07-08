import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    default_chat_id: str
    allowed_chat_ids: set[str]
    allowed_user_ids: set[str]
    send_on_gmail_check: bool
    manual_deploy_command: str
    manual_deploy_timeout_seconds: int


def get_telegram_config() -> TelegramConfig:
    default_chat_id = os.environ.get("TELEGRAM_DEFAULT_CHAT_ID", "").strip()

    allowed_chat_ids = {
        item.strip()
        for item in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if item.strip()
    }
    if default_chat_id:
        allowed_chat_ids.add(default_chat_id)

    allowed_user_ids = {
        item.strip()
        for item in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if item.strip()
    }

    return TelegramConfig(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        default_chat_id=default_chat_id,
        allowed_chat_ids=allowed_chat_ids,
        allowed_user_ids=allowed_user_ids,
        send_on_gmail_check=_env_bool("TELEGRAM_SEND_ON_GMAIL_CHECK", default=False),
        manual_deploy_command=os.environ.get(
            "TELEGRAM_MANUAL_DEPLOY_COMMAND",
            "/usr/local/bin/argus-deploy.sh",
        ).strip(),
        manual_deploy_timeout_seconds=_env_int(
            "TELEGRAM_MANUAL_DEPLOY_TIMEOUT_SECONDS",
            default=300,
        ),
    )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)

    if value is None:
        return default

    try:
        return int(value.strip())
    except ValueError:
        return default
