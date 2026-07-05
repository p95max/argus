from datetime import datetime

from django.utils import timezone

from ..models import MarketplaceAlert, TelegramSettings


def is_quiet_hours_now(at_time: datetime | None = None, settings: TelegramSettings | None = None) -> bool:
    settings = settings or TelegramSettings.load()
    if not settings.quiet_hours_enabled:
        return False

    current_time = timezone.localtime(at_time or timezone.now()).time()
    start = settings.quiet_hours_start
    end = settings.quiet_hours_end

    if start == end:
        return True

    if start < end:
        return start <= current_time < end

    return current_time >= start or current_time < end


def quiet_hours_allows_alert(
    alert: MarketplaceAlert,
    *,
    at_time: datetime | None = None,
    settings: TelegramSettings | None = None,
) -> bool:
    settings = settings or TelegramSettings.load()
    if not is_quiet_hours_now(at_time=at_time, settings=settings):
        return True

    return (
        settings.allow_urgent_during_quiet_hours
        and alert.priority == MarketplaceAlert.Priority.URGENT
    )
