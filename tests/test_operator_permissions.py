from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from alerts.models import MailboxAccount


EXPECTED_OPERATOR_PERMISSIONS = {
    "admin.view_logentry",
    "alerts.view_leadflag",
    "alerts.view_mailboxaccount",
    "alerts.refresh_mailboxaccount",
    "alerts.view_marketplacealert",
    "alerts.view_noisealert",
    "alerts.view_processedemail",
    "alerts.view_serviceevent",
    "alerts.view_telegramsettings",
}


@pytest.mark.django_db
def test_operator_group_is_bootstrapped_with_explicit_permissions():
    group = Group.objects.get(name="operator")

    actual = {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in group.permissions.select_related("content_type")
    }

    assert actual == EXPECTED_OPERATOR_PERMISSIONS


@pytest.mark.django_db
def test_operator_user_can_refresh_gmail_without_mailbox_change_permission(
    client,
    django_user_model,
    monkeypatch,
):
    group = Group.objects.get(name="operator")
    user = django_user_model.objects.create_user(
        username="operator-user",
        password="pass",
        is_staff=True,
    )
    user.groups.add(group)
    mailbox = MailboxAccount.objects.create(
        name="Operator mailbox",
        email="operator@example.local",
    )

    assert user.has_perm("alerts.refresh_mailboxaccount")
    assert not user.has_perm("alerts.change_mailboxaccount")

    monkeypatch.setattr(
        "alerts.admin_site.mailboxes.check_mailbox",
        lambda mailbox: SimpleNamespace(fetched=1, created=1, duplicates=0),
    )
    client.force_login(user)

    response = client.post(
        reverse("admin:alerts_mailboxaccount_gmail_check_now", args=[mailbox.id])
    )

    assert response.status_code == 302
    assert response["Location"] == reverse(
        "admin:alerts_mailboxaccount_change",
        args=[mailbox.id],
    )


@pytest.mark.django_db
def test_staff_without_refresh_permission_cannot_refresh_gmail(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="staff-without-refresh",
        password="pass",
        is_staff=True,
    )
    mailbox = MailboxAccount.objects.create(
        name="Protected mailbox",
        email="protected@example.local",
    )
    client.force_login(user)

    response = client.post(
        reverse("admin:alerts_mailboxaccount_gmail_check_now", args=[mailbox.id])
    )

    assert response.status_code == 403
