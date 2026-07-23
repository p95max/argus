from types import SimpleNamespace

from alerts.telegram import doctor_command


def test_get_environment_label_uses_configured_value(monkeypatch):
    monkeypatch.setenv("ARGUS_ENV_LABEL", "prod")

    assert doctor_command.get_environment_label() == "PROD"


def test_get_environment_label_defaults_to_prod(monkeypatch):
    monkeypatch.delenv("ARGUS_ENV_LABEL", raising=False)

    assert doctor_command.get_environment_label() == "PROD"


def test_build_doctor_script_message_uses_environment_label(monkeypatch):
    monkeypatch.setenv("ARGUS_ENV_LABEL", "prod")
    monkeypatch.setattr(
        doctor_command.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Overall status: HEALTHY\n",
        ),
    )
    monkeypatch.setattr(
        doctor_command,
        "build_git_deploy_status_text",
        lambda: "Git:\nSync: up to date",
    )

    message = doctor_command.build_doctor_script_message()

    assert "🟢 <b>[PROD] Argus: technical check</b>" in message
    assert "📌 <b>Status:</b> OK" in message
    assert "Overall status: HEALTHY" in message
    assert "Sync: up to date" in message


def test_build_doctor_script_message_escapes_environment_label(monkeypatch):
    monkeypatch.setenv("ARGUS_ENV_LABEL", "<prod>")
    monkeypatch.setattr(
        doctor_command.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="OK"),
    )
    monkeypatch.setattr(doctor_command, "build_git_deploy_status_text", lambda: "")

    message = doctor_command.build_doctor_script_message()

    assert "[&lt;PROD&gt;] Argus: technical check" in message
