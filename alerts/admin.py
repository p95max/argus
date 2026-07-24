from .admin_site.alerts import MarketplaceAlertAdmin, NoiseAlertAdmin
from .admin_site.login_logs import AdminLoginLogAdmin
from .admin_site.mailboxes import MailboxAccountAdmin
from .admin_site.mailbox_fetch_period import configure_mailbox_fetch_period_admin
from .admin_site.navigation import configure_admin_navigation
from .admin_site.system import (
    ArgusSettingsAdmin,
    LeadFlagAdmin,
    ProcessedEmailAdmin,
    ServiceEventAdmin,
    TelegramSettingsAdmin,
)
from .admin_site.ui import NeedsAttentionFilter, status_badge
from .telegram.sender import send_telegram_alert


configure_mailbox_fetch_period_admin(MailboxAccountAdmin)
configure_admin_navigation()


__all__ = [
    "NeedsAttentionFilter",
    "status_badge",
    "ArgusSettingsAdmin",
    "AdminLoginLogAdmin",
    "TelegramSettingsAdmin",
    "MailboxAccountAdmin",
    "LeadFlagAdmin",
    "MarketplaceAlertAdmin",
    "NoiseAlertAdmin",
    "ProcessedEmailAdmin",
    "ServiceEventAdmin",
    "send_telegram_alert",
]
