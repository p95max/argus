from types import SimpleNamespace

from alerts.telegram import deploy_command
from alerts.telegram.deploy_command import _build_deploy_message
from alerts.telegram.i18n import override_argus_telegram_language


def test_deploy_queue_message_uses_selected_russian_language():
    with override_argus_telegram_language("ru"):
        message = _build_deploy_message(
            "🚀",
            "Queued",
            "Поставлено в общую фоновую очередь.",
        )

    assert "<b>Argus: развёртывание</b>" in message
    assert "<b>Статус:</b> В очереди" in message


def test_deploy_queue_message_uses_selected_german_language():
    with override_argus_telegram_language("de"):
        message = _build_deploy_message(
            "🚀",
            "Queued",
            "In die gemeinsame Hintergrundwarteschlange gestellt.",
        )

    assert "<b>Argus: Bereitstellung</b>" in message
    assert "<b>Status:</b> In Warteschlange" in message


def test_deploy_request_uses_selected_language(monkeypatch, tmp_path):
    monkeypatch.setattr(deploy_command, "PENDING_REQUEST_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(deploy_command, "ACTIVE_REQUEST_FILE", tmp_path / "active.json")
    monkeypatch.setattr(deploy_command, "_queue_is_busy", lambda: False)
    monkeypatch.setattr(
        deploy_command.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )

    with override_argus_telegram_language("de"):
        result = deploy_command.request_deploy(chat_id="42", user_id="100")

    assert result.ok is True
    assert "<b>Argus: Bereitstellung</b>" in result.message
    assert "<b>Status:</b> In Warteschlange" in result.message
    assert "In die gemeinsame Hintergrundwarteschlange gestellt." in result.message
