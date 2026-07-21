from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_telegram_bot_registers_deploy_command():
    content = (
        ROOT / "alerts" / "management" / "commands" / "run_telegram_bot.py"
    ).read_text()

    assert "from alerts.telegram.deploy_command import handle_deploy_command" in content
    assert 'CommandHandler(\n                "deploy",\n                handle_deploy_command,' in content


def test_sudoers_allows_only_enqueuing_existing_deploy_service():
    content = (ROOT / "deploy" / "sudoers" / "argus-auto-deploy").read_text()

    assert (
        "argus ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block start "
        "argus-auto-deploy.service"
    ) in content
    assert "git commit" not in content
    assert "git push" not in content


def test_sudoers_allows_only_gmail_polling_control_commands():
    content = (ROOT / "deploy" / "sudoers" / "argus-auto-deploy").read_text()

    assert (
        "argus ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now "
        "argus-check-gmail.timer"
    ) in content
    assert (
        "argus ALL=(root) NOPASSWD: /usr/bin/systemctl disable --now "
        "argus-check-gmail.timer"
    ) in content
    assert (
        "argus ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block start "
        "argus-check-gmail.service"
    ) in content


def test_auto_deploy_emits_telegram_lifecycle_notifications():
    content = (ROOT / "deploy" / "scripts" / "argus-auto-deploy.sh").read_text()

    assert 'DEPLOY_NOTIFY_BIN="${DEPLOY_NOTIFY_BIN:-/usr/local/bin/argus-deploy-notify.py}"' in content
    assert 'DEPLOY_RESULT="success"' in content
    assert '"$DEPLOY_NOTIFY_BIN" start' in content
    assert (
        '"$DEPLOY_NOTIFY_BIN" finish --status "$status" '
        '--result "$DEPLOY_RESULT"'
    ) in content
    assert 'DEPLOY_RESULT="up_to_date"' in content
    assert 'DEPLOY_RESULT="updated"' in content
    assert "trap notify_deploy_finish EXIT" in content


def test_doctor_verifies_deployed_notifier():
    content = (ROOT / "deploy" / "scripts" / "argus-doctor.sh").read_text()

    assert "deploy/scripts/argus-deploy-notify.py" in content
    assert 'deployed_path="/usr/local/bin/$(basename "$relative_path")"' in content
    assert '[[ ! -x "$deployed_path" ]]' in content
    assert 'cmp -s "$repo_path" "$deployed_path"' in content
