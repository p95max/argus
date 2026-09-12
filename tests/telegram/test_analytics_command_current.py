import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from alerts.models import Listing, ListingViewStat, MailboxAccount, MarketplaceAlert
from alerts.telegram import analytics_command
from alerts.views.mobile import analytics as mobile_analytics


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeUpdate:
    def __init__(self):
        self.effective_message = FakeMessage()


@pytest.mark.django_db
def test_telegram_analytics_builds_listing_details(monkeypatch):
    now = timezone.now()
    mailbox = MailboxAccount.objects.create(name="Main", email="main@example.local")
    listing = Listing.objects.create(
        title="VW Golf",
        mailbox=mailbox,
        kleinanzeigen_url="https://www.kleinanzeigen.de/s-anzeige/vw-golf/1234567890-216-1234",
        views_count=120,
    )
    old_stat = ListingViewStat.objects.create(listing=listing, views_count=100)
    ListingViewStat.objects.filter(id=old_stat.id).update(created_at=now - timedelta(hours=25))
    MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id=listing.kleinanzeigen_listing_id,
        listing_title=listing.title,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        received_at=now - timedelta(days=2),
    )
    monkeypatch.setattr(
        analytics_command,
        "fetch_listing_public_metadata",
        lambda url: SimpleNamespace(published_on=date.today() - timedelta(days=3)),
    )

    text = analytics_command._build_analytics_message()

    assert "📊 <b>Аналитика</b>" in text
    assert "VW Golf" in text
    assert "120" in text
    assert "за последние 24 ч" in text
    assert "опубликовано 3 дня назад" in text
    assert "последнее обращение 2 дня назад" in text


@pytest.mark.django_db
def test_telegram_analytics_handles_missing_publication_and_inquiry(monkeypatch):
    Listing.objects.create(
        title="Fresh",
        kleinanzeigen_url="https://www.kleinanzeigen.de/s-anzeige/fresh/2234567890-216-1234",
        views_count=5,
    )
    monkeypatch.setattr(
        analytics_command,
        "fetch_listing_public_metadata",
        lambda url: (_ for _ in ()).throw(RuntimeError("blocked")),
    )

    text = analytics_command._build_analytics_message()

    assert "⚪ дата публикации недоступна" in text
    assert "🕒 последнее обращение: данных пока нет" in text


def test_telegram_analytics_helpers_cover_labels_and_periods():
    assert analytics_command._format_count(1234) == "1 234"
    assert analytics_command._format_date(None) == "—"
    assert analytics_command._days_label(0) == "сегодня"
    assert analytics_command._days_label(1) == "вчера"
    assert analytics_command._days_label(2) == "2 дня назад"
    assert analytics_command._days_label(5) == "5 дней назад"
    assert analytics_command._publication_icon(2) == "🟢"
    assert analytics_command._publication_icon(10) == "🟡"
    assert analytics_command._publication_icon(20) == "🔴"
    assert "данных пока нет" in analytics_command._period_views_line("📈", "24 ч", None)
    assert "+7" in analytics_command._period_views_line("📈", "24 ч", 7)


def test_telegram_analytics_handler_checks_permission(monkeypatch):
    update = FakeUpdate()
    monkeypatch.setattr(analytics_command, "is_allowed_update", lambda update: False)

    asyncio.run(analytics_command.handle_analytics_command(update, context=object()))

    assert "does not have access" in update.effective_message.replies[0]["text"]


def test_telegram_analytics_handler_replies_with_html(monkeypatch):
    update = FakeUpdate()
    monkeypatch.setattr(analytics_command, "is_allowed_update", lambda update: True)
    monkeypatch.setattr(analytics_command, "_build_analytics_message", lambda: "<b>Analytics</b>")

    asyncio.run(analytics_command.handle_analytics_command(update, context=object()))

    reply = update.effective_message.replies[0]
    assert reply["text"] == "<b>Analytics</b>"
    assert reply["parse_mode"] == "HTML"
    assert reply["disable_web_page_preview"] is True


@pytest.mark.django_db
def test_mobile_analytics_chart_helpers_group_growth():
    now = timezone.now()
    listing = Listing.objects.create(
        title="VW Golf",
        kleinanzeigen_url="https://www.kleinanzeigen.de/s-anzeige/vw-golf/3234567890-216-1234",
        views_count=130,
    )
    first = ListingViewStat.objects.create(listing=listing, views_count=100)
    second = ListingViewStat.objects.create(listing=listing, views_count=110)
    third = ListingViewStat.objects.create(listing=listing, views_count=130)
    ListingViewStat.objects.filter(id=first.id).update(created_at=now - timedelta(hours=2))
    ListingViewStat.objects.filter(id=second.id).update(created_at=now - timedelta(hours=1))
    ListingViewStat.objects.filter(id=third.id).update(created_at=now)

    events = mobile_analytics._growth_events_by_listing()[listing.id]
    chart_set = mobile_analytics._build_chart_set(events, now)

    assert [delta for _created_at, delta in events] == [10, 20]
    assert len(chart_set["chart_24h"]) == 24
    assert len(chart_set["chart_7d"]) == 7
    assert len(chart_set["chart_hours_all_time"]) == 24
    assert sum(item["value"] for item in chart_set["chart_24h"]) == 30
    assert sum(item["value"] for item in chart_set["chart_7d"]) == 30
    assert sum(item["value"] for item in chart_set["chart_hours_all_time"]) == 30


@pytest.mark.django_db
def test_mobile_analytics_page_renders_for_staff(client):
    user = get_user_model().objects.create_user(
        username="analytics-staff",
        password="pass",
        is_staff=True,
    )
    Listing.objects.create(
        title="VW Golf",
        kleinanzeigen_url="https://www.kleinanzeigen.de/s-anzeige/vw-golf/4234567890-216-1234",
        views_count=42,
    )
    client.force_login(user)

    response = client.get(reverse("mobile_analytics"))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Аналитика" in body
    assert "VW Golf" in body


@pytest.mark.django_db
def test_mobile_analytics_rejects_non_staff(client):
    user = get_user_model().objects.create_user(
        username="analytics-user",
        password="pass",
        is_staff=False,
    )
    client.force_login(user)

    response = client.get(reverse("mobile_analytics"))

    assert response.status_code == 403
