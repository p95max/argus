from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext as _
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import MarketplaceAlert
from .i18n import use_argus_telegram_language


CALLBACK_PREFIX = "alert"
CALLBACK_STATUS_ACTION = "status"
POLLING_CALLBACK_PREFIX = "polling"
POLLING_STATUS_ACTION = "status"
POLLING_ACTIONS = {"status", "enable", "disable", "run_now"}

CALLBACK_STATUS_UPDATES = {
    "in_work": MarketplaceAlert.AlertStatus.IN_WORK,
    "unread": MarketplaceAlert.AlertStatus.UNREAD,
    "ignored": MarketplaceAlert.AlertStatus.IGNORED,
}


@use_argus_telegram_language
def build_alert_keyboard(alert: MarketplaceAlert) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _("Status"),
                    callback_data=_callback_data(alert.id, CALLBACK_STATUS_ACTION),
                ),
            ],
            [
                InlineKeyboardButton(
                    _("Take to work"),
                    callback_data=_callback_data(alert.id, "in_work"),
                ),
                InlineKeyboardButton(
                    _("Release"),
                    callback_data=_callback_data(alert.id, "unread"),
                ),
            ],
            [
                InlineKeyboardButton(
                    _("Ignore"),
                    callback_data=_callback_data(alert.id, "ignored"),
                ),
            ],
            [
                InlineKeyboardButton(
                    _("Open mobile"),
                    url=_mobile_alert_url(alert),
                ),
            ],
        ]
    )


@use_argus_telegram_language
def build_unread_report_keyboard(alerts: list[MarketplaceAlert]) -> InlineKeyboardMarkup | None:
    from .messages import _group_unread_reminder_cases, _truncate

    cases = _group_unread_reminder_cases(alerts)
    if not cases:
        return None

    if len(cases) == 1:
        return build_alert_keyboard(cases[0]["latest"])

    rows = []
    for index, case in enumerate(cases[:5], start=1):
        latest = case["latest"]
        title = latest.listing_title or latest.subject or latest.get_event_type_display()
        rows.append(
            [
                InlineKeyboardButton(
                    f"📱 {index}. {_truncate(title, 44)}",
                    url=_mobile_alert_url(latest),
                ),
            ]
        )

    return InlineKeyboardMarkup(rows)


@use_argus_telegram_language
def build_gmail_polling_keyboard(is_enabled: bool, can_control: bool = True) -> InlineKeyboardMarkup:
    if not can_control:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        _("Refresh status"),
                        callback_data=_polling_callback_data(POLLING_STATUS_ACTION),
                    ),
                ],
            ]
        )

    toggle_action = "disable" if is_enabled else "enable"
    toggle_label = _("Stop polling") if is_enabled else _("Start polling")
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    toggle_label,
                    callback_data=_polling_callback_data(toggle_action),
                ),
                InlineKeyboardButton(
                    _("Run check now"),
                    callback_data=_polling_callback_data("run_now"),
                ),
            ],
            [
                InlineKeyboardButton(
                    _("Refresh status"),
                    callback_data=_polling_callback_data(POLLING_STATUS_ACTION),
                ),
            ],
        ]
    )


def _callback_data(alert_id: int, action: str) -> str:
    return f"{CALLBACK_PREFIX}:{alert_id}:{action}"


def _polling_callback_data(action: str) -> str:
    return f"{POLLING_CALLBACK_PREFIX}:{action}"


def _mobile_alert_url(alert: MarketplaceAlert) -> str:
    path = reverse("mobile_alert_detail", args=[alert.id])
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


def parse_gmail_polling_callback_data(callback_data: str) -> str:
    if not callback_data:
        raise ValueError("Unknown Telegram action.")

    parts = callback_data.split(":")
    if len(parts) != 2 or parts[0] != POLLING_CALLBACK_PREFIX:
        raise ValueError("Unknown Telegram action.")

    action = parts[1]
    if action not in POLLING_ACTIONS:
        raise ValueError("Unknown Telegram action.")

    return action
