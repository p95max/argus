from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTO_DEPLOY_SCRIPT = ROOT / "deploy" / "scripts" / "argus-auto-deploy.sh"


def test_auto_deploy_runs_argus_readiness_check_before_restart():
    script = AUTO_DEPLOY_SCRIPT.read_text(encoding="utf-8")

    django_check = '"$PYTHON_BIN" manage.py check --deploy --fail-level ERROR'
    argus_check = '"$PYTHON_BIN" manage.py argus_check_deploy'
    restart = "run_systemctl restart $RESTART_SERVICES"

    assert django_check in script
    assert argus_check in script
    assert restart in script
    assert script.index(django_check) < script.index(argus_check) < script.index(restart)


def test_auto_deploy_keeps_doctor_after_service_restart():
    script = AUTO_DEPLOY_SCRIPT.read_text(encoding="utf-8")

    restart = "run_systemctl restart $RESTART_SERVICES"
    doctor = "bash deploy/scripts/argus-doctor.sh"

    assert restart in script
    assert doctor in script
    assert script.index(restart) < script.index(doctor)
