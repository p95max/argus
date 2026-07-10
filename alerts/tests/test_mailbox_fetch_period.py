from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from alerts.models import MailboxAccount


class MailboxFetchPeriodTests(TestCase):
    def test_today_period_adds_one_day_filter(self):
        mailbox = MailboxAccount.objects.create(
            name="Today",
            gmail_search_query="from:(kleinanzeigen.de)",
            fetch_period=MailboxAccount.FetchPeriod.TODAY,
        )

        self.assertEqual(
            mailbox.gmail_search_query,
            "from:(kleinanzeigen.de) newer_than:1d",
        )

    def test_last_week_replaces_existing_managed_filter(self):
        mailbox = MailboxAccount.objects.create(
            name="Week",
            gmail_search_query="from:(kleinanzeigen.de) newer_than:1d",
            fetch_period=MailboxAccount.FetchPeriod.LAST_7_DAYS,
        )

        self.assertEqual(
            mailbox.gmail_search_query,
            "from:(kleinanzeigen.de) newer_than:7d",
        )

    def test_no_limit_removes_managed_filter(self):
        mailbox = MailboxAccount.objects.create(
            name="All",
            gmail_search_query="from:(kleinanzeigen.de) newer_than:7d",
            fetch_period=MailboxAccount.FetchPeriod.ALL,
        )

        self.assertEqual(mailbox.gmail_search_query, "from:(kleinanzeigen.de)")

    def test_non_superuser_cannot_edit_fetch_period_in_admin(self):
        from alerts import admin as alerts_admin  # noqa: F401

        user = get_user_model().objects.create_user(
            username="staff",
            password="test",
            is_staff=True,
        )
        request = RequestFactory().get("/control/alerts/mailboxaccount/1/change/")
        request.user = user
        model_admin = admin.site._registry[MailboxAccount]

        self.assertIn("fetch_period", model_admin.get_readonly_fields(request))

    def test_superuser_can_edit_fetch_period_in_admin(self):
        from alerts import admin as alerts_admin  # noqa: F401

        user = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.com",
            password="test",
        )
        request = RequestFactory().get("/control/alerts/mailboxaccount/1/change/")
        request.user = user
        model_admin = admin.site._registry[MailboxAccount]

        self.assertNotIn("fetch_period", model_admin.get_readonly_fields(request))
