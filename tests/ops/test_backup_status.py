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
