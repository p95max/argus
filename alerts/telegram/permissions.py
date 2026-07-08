from .config import get_telegram_config


def is_allowed_update(update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    return is_allowed_telegram_actor(
        chat_id=chat_id,
        user_id=user_id,
    )


def is_default_chat_update(update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return is_default_chat(chat_id)


def is_allowed_chat(chat_id: str) -> bool:
    config = get_telegram_config()

    if not config.allowed_chat_ids:
        return False

    return str(chat_id) in config.allowed_chat_ids


def is_default_chat(chat_id: str) -> bool:
    config = get_telegram_config()
    return bool(config.default_chat_id) and str(chat_id) == config.default_chat_id


def is_allowed_telegram_actor(chat_id: str, user_id: str = "") -> bool:
    config = get_telegram_config()

    if not config.allowed_chat_ids:
        return False

    if str(chat_id) not in config.allowed_chat_ids:
        return False

    if not config.allowed_user_ids:
        return True

    return bool(user_id) and str(user_id) in config.allowed_user_ids
