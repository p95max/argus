from types import SimpleNamespace

from alerts.telegram import deploy_command


def configure_request_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        deploy_command,
        "PENDING_REQUEST_FILE",
        tmp_path / "pending.json",
    )
    monkeypatch.setattr(
        deploy_command,
        "ACTIVE_REQUEST_FILE",
        tmp_path / "active.json",
    )
    monkeypatch.setattr(
        deploy_command,
        "QUEUE_LOCK_FILE",
        tmp_path / "queue.lock",
    )


def test_request_deploy_starts_service_when_queue_is_free(monkeypatch, tmp_path):
    configure_request_paths(monkeypatch, tmp_path)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == deploy_command.SYSTEMCTL_BIN:
            return SimpleNamespace(returncode=0, stdout="inactive\n")
        if command[0] == deploy_command.FLOCK_BIN:
            return SimpleNamespace(returncode=0, stdout="")
        if command[0] == deploy_command.SUDO_BIN:
            return SimpleNamespace(returncode=0, stdout="")
        raise AssertionError(command)

    monkeypatch.setattr(deploy_command.subprocess, "run", fake_run)

    result = deploy_command.request_deploy(chat_id="123", user_id="456")

    assert result.ok is True
    assert "поставлен в общую очередь" in result.message
    assert "запуск ожидается сейчас" in result.message
    assert deploy_command.PENDING_REQUEST_FILE.exists()
    assert [
        deploy_command.SUDO_BIN,
        "-n",
        deploy_command.SYSTEMCTL_BIN,
        "--no-block",
        "start",
        deploy_command.DEPLOY_SERVICE,
    ] in commands


def test_request_deploy_reports_busy_queue_deadline(monkeypatch, tmp_path):
    configure_request_paths(monkeypatch, tmp_path)

    def fake_run(command, **kwargs):
        if command[0] == deploy_command.SYSTEMCTL_BIN:
            return SimpleNamespace(returncode=0, stdout="inactive\n")
        if command[0] == deploy_command.FLOCK_BIN:
            return SimpleNamespace(returncode=1, stdout="")
        if command[0] == deploy_command.SUDO_BIN:
            return SimpleNamespace(returncode=0, stdout="")
        raise AssertionError(command)

    monkeypatch.setattr(deploy_command.subprocess, "run", fake_run)

    result = deploy_command.request_deploy(chat_id="123")

    assert result.ok is True
    assert "Общая очередь занята" in result.message
    assert "Ориентир запуска: до" in result.message
    assert "15" not in result.message or "тайм-ауту" in result.message


def test_request_deploy_does_not_enqueue_duplicate_active_service(monkeypatch, tmp_path):
    configure_request_paths(monkeypatch, tmp_path)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="activating\n")

    monkeypatch.setattr(deploy_command.subprocess, "run", fake_run)

    result = deploy_command.request_deploy(chat_id="123")

    assert result.ok is True
    assert "уже выполняется или ожидает" in result.message
    assert not deploy_command.PENDING_REQUEST_FILE.exists()
    assert len(commands) == 1


def test_request_deploy_removes_request_when_systemctl_fails(monkeypatch, tmp_path):
    configure_request_paths(monkeypatch, tmp_path)

    def fake_run(command, **kwargs):
        if command[0] == deploy_command.SYSTEMCTL_BIN:
            return SimpleNamespace(returncode=0, stdout="inactive\n")
        if command[0] == deploy_command.FLOCK_BIN:
            return SimpleNamespace(returncode=0, stdout="")
        if command[0] == deploy_command.SUDO_BIN:
            return SimpleNamespace(returncode=1, stdout="permission <denied>")
        raise AssertionError(command)

    monkeypatch.setattr(deploy_command.subprocess, "run", fake_run)

    result = deploy_command.request_deploy(chat_id="123")

    assert result.ok is False
    assert "permission &lt;denied&gt;" in result.message
    assert not deploy_command.PENDING_REQUEST_FILE.exists()
