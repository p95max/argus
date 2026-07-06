from django.conf import settings
from django.urls import reverse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import MarketplaceAlert


CALLBACK_PREFIX = "alert"
CALLBACK_STATUS_ACTION = "status"

CALLBACK_STATUS_UPDATES = {
    "in_work": MarketplaceAlert.AlertStatus.IN_WORK,
    "unread": MarketplaceAlert.AlertStatus.UNREAD,
    "ignored": MarketplaceAlert.AlertStatus.IGNORED,
}


def build_alert_keyboard(alert: MarketplaceAlert) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Статус",
                    callback_data=_callback_data(alert.id, CALLBACK_STATUS_ACTION),
                ),
            ],
            [
                InlineKeyboardButton(
                    "В работу",
                    callback_data=_callback_data(alert.id, "in_work"),
                ),
                InlineKeyboardButton(
                    "Снять / не в работе",
                    callback_data=_callback_data(alert.id, "unread"),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Игнор",
                    callback_data=_callback_data(alert.id, "ignored"),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Open in Admin",
                    url=_admin_alert_url(alert),
                ),
            ],
        ]
    )


def _callback_data(alert_id: int, action: str) -> str:
    return f"{CALLBACK_PREFIX}:{alert_id}:{action}"


def _admin_alert_url(alert: MarketplaceAlert) -> str:
    path = reverse("admin:alerts_marketplacealert_change", args=[alert.id])
    base_url = getattr(settings, "ARGUS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return f"{base_url}{path}"
    return path


def _parse_callback_data(callback_data: str) -> tuple[int, str]:
    if not callback_data:
        raise ValueError("Unknown Telegram action.")

    parts = callback_data.split(":")

    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        raise ValueError("Unknown Telegram action.")

    action = parts[2]
    if action != CALLBACK_STATUS_ACTION and action not in CALLBACK_STATUS_UPDATES:
        raise ValueError("Unknown Telegram action.")

    try:
        alert_id = int(parts[1])
    except ValueError as exc:
        raise ValueError("Unknown Telegram alert.") from exc

    return alert_id, action
