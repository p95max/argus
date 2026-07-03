from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from alerts.gmail.gmail import MailboxCheckResult
from alerts.models import MailboxAccount


@pytest.mark.django_db
def test_check_gmail_command_checks_all_active_mailboxes(monkeypatch):
    active_one = MailboxAccount.objects.create(name="One", email="one@example.local", is_active=True)
    active_two = MailboxAccount.objects.create(name="Two", email="two@example.local", is_active=True)
    MailboxAccount.objects.create(name="Off", email="off@example.local", is_active=False)
    checked = []

    def fake_check_mailbox(mailbox, service=None, max_results=25):
        checked.append((mailbox.email, max_results))
        return MailboxCheckResult(fetched=0, created=0, duplicates=0)

    monkeypatch.setattr("alerts.management.commands.check_gmail.check_mailbox", fake_check_mailbox)
    stdout = StringIO()

    call_command("check_gmail", "--max-results", "7", stdout=stdout)

    assert checked == [(active_one.email, 7), (active_two.email, 7)]
    assert "Created 0, duplicates 0, failed 0" in stdout.getvalue()


@pytest.mark.django_db
def test_check_gmail_command_continues_after_mailbox_error(monkeypatch):
    MailboxAccount.objects.create(name="Bad", email="bad@example.local", is_active=True)
    MailboxAccount.objects.create(name="Good", email="good@example.local", is_active=True)


    def fake_check_mailbox(mailbox, service=None, max_results=25):
        if mailbox.email == "bad@example.local":
            raise RuntimeError("boom")
        return MailboxCheckResult(fetched=1, created=1, duplicates=0)

    monkeypatch.setattr("alerts.management.commands.check_gmail.check_mailbox", fake_check_mailbox)
    stdout = StringIO()
    stderr = StringIO()

    call_command("check_gmail", stdout=stdout, stderr=stderr)

    assert "bad@example.local: boom" in stderr.getvalue()
    assert "good@example.local: fetched 1, created 1, duplicates 0" in stdout.getvalue()
    assert "Created 1, duplicates 0, failed 1" in stdout.getvalue()


@pytest.mark.django_db
def test_check_gmail_command_handles_zero_new_messages(monkeypatch):
    MailboxAccount.objects.create(name="Empty", email="empty@example.local", is_active=True)

    monkeypatch.setattr(
        "alerts.management.commands.check_gmail.check_mailbox",
        lambda mailbox, service=None, max_results=25: MailboxCheckResult(fetched=0, created=0, duplicates=0),
    )
    stdout = StringIO()

    call_command("check_gmail", stdout=stdout)

    assert "empty@example.local: fetched 0, created 0, duplicates 0" in stdout.getvalue()
    assert "Done. Created 0, duplicates 0, failed 0." in stdout.getvalue()


@pytest.mark.django_db
def test_check_gmail_command_requires_active_mailbox():
    with pytest.raises(CommandError, match="No active mailboxes found"):
        call_command("check_gmail")
