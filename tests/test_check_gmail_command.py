from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from alerts.gmail.gmail import MailboxCheckResult
from alerts.models import MailboxAccount, ServiceEvent


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
    assert "Done. Created 0, duplicates 0, failed 0, skipped 0." in stdout.getvalue()


@pytest.mark.django_db
def test_check_gmail_command_requires_active_mailbox():
    with pytest.raises(CommandError, match="No active mailboxes found"):
        call_command("check_gmail")


@pytest.mark.django_db
def test_check_gmail_command_disables_active_mailbox_without_email(monkeypatch):
    mailbox = MailboxAccount.objects.create(name="No email", email="", is_active=True)
    ServiceEvent.objects.create(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        status=ServiceEvent.Status.OPEN,
        source="gmail.check_mailbox",
        title="Mailbox error",
        fingerprint=f"mailbox:{mailbox.id}:gmail_check",
        mailbox=mailbox,
    )
    called = []
    monkeypatch.setattr(
        "alerts.management.commands.check_gmail.check_mailbox",
        lambda mailbox, service=None, max_results=25: called.append(mailbox.id),
    )
    stdout = StringIO()
    stderr = StringIO()

    call_command("check_gmail", stdout=stdout, stderr=stderr)

    mailbox.refresh_from_db()
    event = ServiceEvent.objects.get()
    assert called == []
    assert mailbox.is_active is False
    assert event.status == ServiceEvent.Status.RECOVERED
    assert "skipped and disabled because email is empty" in stderr.getvalue()
    assert "Skipped 1" in stdout.getvalue()


@pytest.mark.django_db
def test_check_gmail_command_disables_mailbox_when_token_file_missing(monkeypatch):
    mailbox = MailboxAccount.objects.create(name="Missing token", email="missing@example.local", is_active=True)
    ServiceEvent.objects.create(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        status=ServiceEvent.Status.OPEN,
        source="gmail.check_mailbox",
        title="Mailbox error",
        fingerprint=f"mailbox:{mailbox.id}:gmail_check",
        mailbox=mailbox,
    )

    def fake_check_mailbox(mailbox, service=None, max_results=25):
        raise FileNotFoundError("token.json")

    monkeypatch.setattr("alerts.management.commands.check_gmail.check_mailbox", fake_check_mailbox)
    stdout = StringIO()
    stderr = StringIO()

    call_command("check_gmail", stdout=stdout, stderr=stderr)

    mailbox.refresh_from_db()
    event = ServiceEvent.objects.get()
    assert mailbox.is_active is False
    assert event.status == ServiceEvent.Status.RECOVERED
    assert "missing@example.local: skipped and disabled" in stderr.getvalue()
    assert "Done. Created 0, duplicates 0, failed 0, skipped 1." in stdout.getvalue()


@pytest.mark.django_db
def test_check_gmail_command_filters_by_mailbox_id(monkeypatch):
    target = MailboxAccount.objects.create(name="Target", email="target@example.local", is_active=True)
    MailboxAccount.objects.create(name="Other", email="other@example.local", is_active=True)
    checked = []

    def fake_check_mailbox(mailbox, service=None, max_results=25):
        checked.append(mailbox.email)
        return MailboxCheckResult(fetched=1, created=0, duplicates=1)

    monkeypatch.setattr("alerts.management.commands.check_gmail.check_mailbox", fake_check_mailbox)

    call_command("check_gmail", "--mailbox", str(target.id), stdout=StringIO())

    assert checked == ["target@example.local"]
