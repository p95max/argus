from alerts import backup_status


def test_backup_status_handles_linux_without_systemd(monkeypatch):
    monkeypatch.setattr(
        backup_status,
        "_run_systemctl",
        lambda args: backup_status.CommandResult(
            1,
            "",
            "Failed to connect to bus: Host is down",
        ),
    )

    status = backup_status.get_backup_status()

    assert status.is_available is False
    assert status.is_healthy is False


def test_backup_status_handles_systemd_bus_error_after_enabled_check(monkeypatch):
    responses = iter(
        [
            backup_status.CommandResult(0, "disabled", ""),
            backup_status.CommandResult(1, "", "Failed to connect to bus: Host is down"),
            backup_status.CommandResult(
                1,
                "",
                "System has not been booted with systemd as init system (PID 1).",
            ),
        ]
    )
    monkeypatch.setattr(backup_status, "_run_systemctl", lambda args: next(responses))

    status = backup_status.get_backup_status()

    assert status.is_available is False
