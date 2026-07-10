import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "deploy" / "scripts" / "argus-deploy-notify.py"


def load_module():
    spec = importlib.util.spec_from_file_location("argus_deploy_notify", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def configure_notification_module(monkeypatch, tmp_path):
    module = load_module()
    pending = tmp_path / "pending.json"
    active = tmp_path / "active.json"
    sent = []

    monkeypatch.setattr(module, "PENDING_REQUEST_FILE", pending)
    monkeypatch.setattr(module, "ACTIVE_REQUEST_FILE", active)
    monkeypatch.setattr(
        module,
        "load_env",
        lambda: {
            "TELEGRAM_BOT_TOKEN": "token",
            "ARGUS_ENV_LABEL": "TEST",
        },
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda token, chat_id, text: sent.append((token, chat_id, text)) or True,
    )
    monkeypatch.setattr(module, "current_head", lambda: "abc1234")

    return module, pending, active, sent


def test_deploy_notification_lifecycle(monkeypatch, tmp_path):
    module, pending, active, sent = configure_notification_module(monkeypatch, tmp_path)

    pending.write_text(
        json.dumps(
            {
                "chat_id": "123",
                "user_id": "456",
                "requested_at": 1,
            }
        )
    )

    assert module.handle_start() == 0
    assert not pending.exists()
    assert active.exists()
    assert len(sent) == 1
    assert "deploy started" in sent[0][2]
    assert "Queue wait:" in sent[0][2]

    assert module.handle_finish(0, "updated") == 0
    assert not active.exists()
    assert len(sent) == 2
    assert "deploy finished" in sent[1][2]
    assert "Status: UPDATED" in sent[1][2]
    assert "HEAD: abc1234" in sent[1][2]


def test_up_to_date_deploy_reports_no_redeploy(monkeypatch, tmp_path):
    module, _, active, sent = configure_notification_module(monkeypatch, tmp_path)
    active.write_text(json.dumps({"chat_id": "123", "started_at": 1}))

    assert module.handle_finish(0, "up_to_date") == 0

    assert not active.exists()
    assert len(sent) == 1
    assert "deploy check finished" in sent[0][2]
    assert "Status: UP TO DATE" in sent[0][2]
    assert "HEAD: abc1234" in sent[0][2]
    assert "services were not redeployed" in sent[0][2]


def test_timer_deploy_without_telegram_request_sends_nothing(monkeypatch, tmp_path):
    module = load_module()
    sent = []

    monkeypatch.setattr(module, "PENDING_REQUEST_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(module, "ACTIVE_REQUEST_FILE", tmp_path / "active.json")
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda token, chat_id, text: sent.append(text) or True,
    )

    assert module.handle_start() == 0
    assert module.handle_finish(0, "up_to_date") == 0
    assert sent == []


def test_failed_deploy_sends_failure_notification(monkeypatch, tmp_path):
    module = load_module()
    active = tmp_path / "active.json"
    sent = []

    monkeypatch.setattr(module, "PENDING_REQUEST_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(module, "ACTIVE_REQUEST_FILE", active)
    monkeypatch.setattr(
        module,
        "load_env",
        lambda: {
            "TELEGRAM_BOT_TOKEN": "token",
            "ARGUS_ENV_LABEL": "TEST",
        },
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda token, chat_id, text: sent.append(text) or True,
    )

    active.write_text(json.dumps({"chat_id": "123", "started_at": 1}))

    assert module.handle_finish(7, "success") == 0
    assert not active.exists()
    assert len(sent) == 1
    assert "deploy failed" in sent[0]
    assert "Exit status: 7" in sent[0]
