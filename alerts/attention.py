from django.db.models import Q, QuerySet

from .models import MailboxAccount, MarketplaceAlert


def needs_attention_alert_q() -> Q:
    return (
        Q(alert_status=MarketplaceAlert.AlertStatus.UNREAD)
        | Q(priority__in=[MarketplaceAlert.Priority.HIGH, MarketplaceAlert.Priority.URGENT])
        | Q(parse_status__in=[MarketplaceAlert.ParseStatus.ERROR, MarketplaceAlert.ParseStatus.PARTIAL])
        | Q(mailbox__connection_status=MailboxAccount.ConnectionStatus.ERROR)
        | Q(telegram_error__gt="")
    )


def filter_needs_attention(queryset: QuerySet[MarketplaceAlert]) -> QuerySet[MarketplaceAlert]:
    return queryset.filter(needs_attention_alert_q()).distinct()


def alert_needs_attention(alert: MarketplaceAlert) -> bool:
    if alert.alert_status == MarketplaceAlert.AlertStatus.UNREAD:
        return True
    if alert.priority in [MarketplaceAlert.Priority.HIGH, MarketplaceAlert.Priority.URGENT]:
        return True
    if alert.parse_status in [MarketplaceAlert.ParseStatus.ERROR, MarketplaceAlert.ParseStatus.PARTIAL]:
        return True
    if alert.telegram_error:
        return True
    return alert.mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR
