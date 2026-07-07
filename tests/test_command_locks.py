from io import StringIO

import pytest
from django.core.management import call_command
from django.conf import settings

from alerts.models import MailboxAccount


def _lock_file(name):
    lock_dir = settings.BASE_DIR / "tmp" / "command_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{name}.lock"
    path.write_text("locked", encoding="utf-8")
    return path


@pytest.mark.django_db
def test_check_gmail_command_skips_when_lock_is_held(monkeypatch):
    MailboxAccount.objects.create(name="Locked", email="locked@example.local", is_active=True)
    lock_path = _lock_file("check_gmail")
    called = []
    monkeypatch.setattr(
        "alerts.management.commands.check_gmail.check_mailbox",
        lambda mailbox, service=None, max_results=25: called.append(mailbox.id),
    )
    stdout = StringIO()

    call_command("check_gmail", stdout=stdout)

    assert called == []
    assert "check_gmail is already running" in stdout.getvalue()
    lock_path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_cleanup_old_leads_command_skips_when_lock_is_held(monkeypatch):
    lock_path = _lock_file("cleanup_old_leads")
    called = []
    monkeypatch.setattr(
        "alerts.management.commands.cleanup_old_leads.cleanup_old_leads",
        lambda **kwargs: called.append(kwargs),
    )
    stdout = StringIO()

    call_command("cleanup_old_leads", stdout=stdout)

    assert called == []
    assert "cleanup_old_leads is already running" in stdout.getvalue()
    lock_path.unlink(missing_ok=True)
