from django.contrib import messages
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .gmail_polling import GmailPollingCommandError, apply_gmail_polling_action
from .permissions import can_manage_mailboxes


@require_POST
def gmail_polling_action(request, action: str):
    if not can_manage_mailboxes(request.user):
        raise PermissionDenied("You do not have permission to manage Gmail polling.")

    try:
        message = apply_gmail_polling_action(action)
    except (GmailPollingCommandError, ValueError) as exc:
        messages.error(
            request,
            _("Gmail polling action failed: %(error)s") % {"error": str(exc)},
        )
    else:
        messages.success(request, message)

    return redirect(_safe_next_url(request))


def _safe_next_url(request):
    admin_prefix = f"/{settings.DJANGO_ADMIN_URL.strip('/')}/"
    fallback_name = "admin:index" if request.path.startswith(admin_prefix) else "mobile_dashboard"
    fallback = reverse(fallback_name)
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback
