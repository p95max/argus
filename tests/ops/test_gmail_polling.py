import pytest

from alerts.gmail_polling import (
    CommandResult,
    GmailPollingCommandError,
    apply_gmail_polling_action,
    get_gmail_polling_status,
)


def test_gmail_polling_status_reads_real_systemd_states(monkeypatch):
    calls = []

    def fake_run_command(command, timeout=8):
        calls.append(command)
        if command[:2] == ["/usr/bin/systemctl", "is-enabled"]:
            return CommandResult(0, "enabled", "")
        if command[:2] == ["/usr/bin/systemctl", "is-active"]:
            return CommandResult(0, "active", "")
        if command[1] == "show":
            return CommandResult(
                0,
                "NextElapseUSecRealtime=Mon 2026-07-20 14:20:00 CEST",
                "",
            )
        if command[1] == "cat":
            return CommandResult(0, "[Timer]\nOnUnitActiveSec=15min", "")
        return CommandResult(1, "", "unexpected command")

    monkeypatch.setattr("alerts.gmail_polling._run_command", fake_run_command)

    status = get_gmail_polling_status()

    assert status.is_enabled is True
    assert status.is_active is True
    assert status.next_run_label == "14:20"
    assert status.interval_label == "15 minutes"
    assert calls == [
        ["/usr/bin/systemctl", "is-enabled", "argus-check-gmail.timer"],
        ["/usr/bin/systemctl", "is-active", "argus-check-gmail.timer"],
        [
            "/usr/bin/systemctl",
            "show",
            "argus-check-gmail.timer",
            "--property=NextElapseUSecRealtime",
        ],
        ["/usr/bin/systemctl", "cat", "argus-check-gmail.timer"],
    ]


def test_gmail_polling_status_falls_back_to_timer_listing(monkeypatch):
    def fake_run_command(command, timeout=8):
        if command[1] == "is-enabled":
            return CommandResult(0, "enabled", "")
        if command[1] == "is-active":
            return CommandResult(0, "active", "")
        if command[1] == "show":
            return CommandResult(0, "NextElapseUSecRealtime=", "")
        if command[1] == "list-timers":
            return CommandResult(
                0,
                "Mon 2026-07-20 14:45:00 CEST 10min left - - argus-check-gmail.timer",
                "",
            )
        if command[1] == "cat":
            return CommandResult(0, "[Timer]\nOnUnitActiveSec=15min", "")
        return CommandResult(1, "", "unexpected command")

    monkeypatch.setattr("alerts.gmail_polling._run_command", fake_run_command)

    status = get_gmail_polling_status()

    assert status.next_run_label == "14:45"
    assert status.interval_label == "15 minutes"


def test_gmail_polling_status_reports_systemd_show_error(monkeypatch):
    def fake_run_command(command, timeout=8):
        if command[:2] == ["/usr/bin/systemctl", "is-enabled"]:
            return CommandResult(1, "disabled", "")
        if command[:2] == ["/usr/bin/systemctl", "is-active"]:
            return CommandResult(3, "inactive", "")
        return CommandResult(1, "", "timer not found")

    monkeypatch.setattr("alerts.gmail_polling._run_command", fake_run_command)

    status = get_gmail_polling_status()

    assert status.is_enabled is False
    assert status.is_active is False
    assert status.error == "timer not found"


def test_gmail_polling_status_handles_missing_systemctl(monkeypatch):
    calls = []

    def fake_run_command(command, timeout=8):
        calls.append(command)
        return CommandResult(127, "", "[Errno 2] No such file or directory: 'systemctl'")

    monkeypatch.setattr("alerts.gmail_polling._run_command", fake_run_command)

    status = get_gmail_polling_status()

    assert status.enabled_state == "unavailable"
    assert status.active_state == "unavailable"
    assert status.enabled_label == "Unavailable"
    assert status.active_label == "unavailable"
    assert status.is_available is False
    assert status.next_run_label == "not scheduled"
    assert status.interval_label == "unknown"
    assert status.error == "systemctl is not available on this system."
    assert calls == [["/usr/bin/systemctl", "is-enabled", "argus-check-gmail.timer"]]


def test_gmail_polling_actions_use_sudo_systemctl(monkeypatch):
    calls = []

    def fake_run_command(command, timeout=8):
        calls.append((command, timeout))
        return CommandResult(0, "", "")

    monkeypatch.setattr("alerts.gmail_polling._run_command", fake_run_command)

    assert apply_gmail_polling_action("enable") == "Gmail polling enabled."
    assert apply_gmail_polling_action("disable") == "Gmail polling disabled."
    assert apply_gmail_polling_action("run_now") == "Gmail check started."

    assert calls == [
        (["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "enable", "--now", "argus-check-gmail.timer"], 20),
        (["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "disable", "--now", "argus-check-gmail.timer"], 20),
        (
            ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "--no-block", "start", "argus-check-gmail.service"],
            20,
        ),
    ]


def test_gmail_polling_action_raises_command_error(monkeypatch):
    monkeypatch.setattr(
        "alerts.gmail_polling._run_command",
        lambda command, timeout=8: CommandResult(1, "", "sudo denied"),
    )

    with pytest.raises(GmailPollingCommandError, match="sudo denied"):
        apply_gmail_polling_action("enable")
