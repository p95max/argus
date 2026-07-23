import asyncio
import logging

from telegram import Bot

from .config import get_telegram_config
from .help_command import build_bot_commands_for_language


logger = logging.getLogger(__name__)


async def publish_telegram_command_menu(bot: Bot, language: str) -> int:
    commands = build_bot_commands_for_language(language)
    await bot.set_my_commands(commands)
    return len(commands)


def refresh_telegram_command_menu(language: str) -> bool:
    config = get_telegram_config()
    if not config.bot_token:
        logger.warning("Telegram command menu was not updated: bot token is missing.")
        return False

    try:
        count = asyncio.run(
            publish_telegram_command_menu(Bot(token=config.bot_token), language)
        )
    except Exception:
        logger.exception("Could not update Telegram command menu.")
        return False

    logger.info(
        "Updated %s Telegram command descriptions for language=%s.",
        count,
        language,
    )
    return True
