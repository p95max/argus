import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "scripts"
    / "argus-health-notify.py"
)


def load_health_notify_module():
    spec = importlib.util.spec_from_file_location("argus_health_notify", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_health_monitor_checks_remote_backup_sync_timer():
    module = load_health_notify_module()

    assert "argus-sync-db-to-neon.timer" in module.TIMERS


def configure_main(monkeypatch, module, *, checks, previous_state=None):
    check_results = iter(checks)
    sent_messages = []
    saved_states = []
    slept = []

    monkeypatch.setattr(
        module,
        "load_env",
        lambda: {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_DEFAULT_CHAT_ID": "123",
            "ARGUS_ENV_LABEL": "TEST",
        },
    )
    monkeypatch.setattr(module, "load_state", lambda: previous_state or {})
    monkeypatch.setattr(module, "collect_problems", lambda env: next(check_results))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(
        module,
        "try_send_telegram",
        lambda token, chat_id, text: sent_messages.append(text) or True,
    )
    monkeypatch.setattr(module, "save_state", lambda state: saved_states.append(state))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH)])

    return sent_messages, saved_states, slept


def test_transient_failure_clears_without_telegram_alert(monkeypatch):
    module = load_health_notify_module()
    sent_messages, saved_states, slept = configure_main(
        monkeypatch,
        module,
        checks=[
            ["Service not active: argus-web.service"],
            [],
        ],
        previous_state={"status": "ok", "problem_hash": ""},
    )

    assert module.main() == 0
    assert slept == [module.FAILURE_CONFIRM_SECONDS]
    assert sent_messages == []
    assert saved_states[-1]["status"] == "ok"
    assert saved_states[-1]["problem_hash"] == ""


def test_persistent_failure_is_sent_after_confirmation(monkeypatch):
    module = load_health_notify_module()
    problem = "Service not active: argus-web.service"
    sent_messages, saved_states, slept = configure_main(
        monkeypatch,
        module,
        checks=[[problem], [problem]],
        previous_state={"status": "ok", "problem_hash": ""},
    )

    assert module.main() == 0
    assert slept == [module.FAILURE_CONFIRM_SECONDS]
    assert len(sent_messages) == 1
    assert "ARGUS: TECHNICAL ALERT" in sent_messages[0]
    assert "Component: health monitor" in sent_messages[0]
    assert "Status: CRITICAL" in sent_messages[0]
    assert problem in sent_messages[0]
    assert saved_states[-1]["status"] == "fail"
    assert saved_states[-1]["problem_hash"]


def test_unchanged_active_failure_is_not_delayed_or_resent(monkeypatch):
    module = load_health_notify_module()
    problem = "Service not active: argus-web.service"
    _, problem_hash = module.problem_fingerprint([problem])
    sent_messages, saved_states, slept = configure_main(
        monkeypatch,
        module,
        checks=[[problem]],
        previous_state={"status": "fail", "problem_hash": problem_hash},
    )

    assert module.main() == 0
    assert slept == []
    assert sent_messages == []
    assert saved_states[-1]["status"] == "fail"
    assert saved_states[-1]["problem_hash"] == problem_hash
