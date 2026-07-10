from django.urls import resolve, reverse

from alerts import mobile


def test_global_mobile_gmail_check_route_uses_global_view():
    url = reverse("mobile_check_gmail_now")
    match = resolve(url)

    assert url == "/m/gmail/check-now/"
    assert match.func is mobile.mobile_check_gmail_now
    assert match.kwargs == {}


def test_mailbox_mobile_gmail_check_route_uses_mailbox_view():
    url = reverse("mobile_check_mailbox_now", args=[123])
    match = resolve(url)

    assert url == "/m/mailboxes/123/check-now/"
    assert match.func is mobile.mobile_check_mailbox_now
    assert match.kwargs == {"mailbox_id": 123}
