import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "deploy" / "scripts" / "argus-run-background-job.sh"
RUNNER_COMMAND = ["bash", str(RUNNER)]
SYSTEMD_DIR = ROOT / "deploy" / "systemd"

QUEUED_SERVICES = {
    "argus-check-gmail.service": "argus-check-gmail",
    "argus-unread-reminders.service": "argus-unread-reminders",
    "argus-cleanup-old-leads.service": "argus-cleanup-old-leads",
    "argus-auto-deploy.service": "argus-auto-deploy",
    "argus-backup-db.service": "argus-backup-db",
}


def test_background_services_use_shared_queue_runner():
    for service_name, job_name in QUEUED_SERVICES.items():
        content = (SYSTEMD_DIR / service_name).read_text()
        assert "TimeoutStartSec=30min" in content
        assert (
            "ExecStart=/usr/local/bin/argus-run-background-job.sh "
            f"{job_name} "
        ) in content


def test_health_monitor_remains_independent_from_background_queue():
    content = (SYSTEMD_DIR / "argus-health-monitor.service").read_text()
    assert "argus-run-background-job.sh" not in content
    assert "argus-health-notify.py" in content


def test_doctor_verifies_deployed_queue_runner():
    content = (ROOT / "deploy" / "scripts" / "argus-doctor.sh").read_text()
    assert "check_executable /usr/local/bin/argus-run-background-job.sh" in content
    assert (
        "check_deployed_copy deploy/scripts/argus-run-background-job.sh"
        in content
    )


@pytest.mark.skipif(
    os.name == "nt",
    reason="The production queue runner uses bash and flock.",
)
def test_runner_serializes_concurrent_jobs(tmp_path):
    queue_lock = tmp_path / "queue.lock"
    order_file = tmp_path / "order.txt"
    quoted_order_file = shlex.quote(str(order_file))
    env = {
        **os.environ,
        "ARGUS_BACKGROUND_QUEUE_LOCK_FILE": str(queue_lock),
        "ARGUS_BACKGROUND_QUEUE_WAIT_SECONDS": "5",
    }

    first = subprocess.Popen(
        [
            *RUNNER_COMMAND,
            "argus-test-first",
            "bash",
            "-c",
            f"sleep 0.4; printf 'first\\n' >> {quoted_order_file}",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    time.sleep(0.1)
    second = subprocess.run(
        [
            *RUNNER_COMMAND,
            "argus-test-second",
            "bash",
            "-c",
            f"printf 'second\\n' >> {quoted_order_file}",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    first_output, _ = first.communicate(timeout=5)

    assert first.returncode == 0, first_output
    assert second.returncode == 0, second.stdout + second.stderr
    assert order_file.read_text().splitlines() == ["first", "second"]
    assert "acquired background-job lock" in first_output
    assert "acquired background-job lock" in second.stdout


@pytest.mark.skipif(
    os.name == "nt",
    reason="The production queue runner uses bash and flock.",
)
def test_runner_skips_duplicate_job_before_queueing(tmp_path):
    queue_lock = tmp_path / "queue.lock"
    order_file = tmp_path / "order.txt"
    quoted_order_file = shlex.quote(str(order_file))
    job_name = f"argus-test-duplicate-{os.getpid()}"
    env = {
        **os.environ,
        "ARGUS_BACKGROUND_QUEUE_LOCK_FILE": str(queue_lock),
        "ARGUS_BACKGROUND_QUEUE_WAIT_SECONDS": "5",
    }

    first = subprocess.Popen(
        [
            *RUNNER_COMMAND,
            job_name,
            "bash",
            "-c",
            f"sleep 0.4; printf 'first\\n' >> {quoted_order_file}",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    time.sleep(0.1)
    duplicate = subprocess.run(
        [
            *RUNNER_COMMAND,
            job_name,
            "bash",
            "-c",
            f"printf 'duplicate\\n' >> {quoted_order_file}",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    first_output, _ = first.communicate(timeout=5)

    assert first.returncode == 0, first_output
    assert duplicate.returncode == 0, duplicate.stdout + duplicate.stderr
    assert "duplicate job is already running or waiting; skipping" in duplicate.stdout
    assert order_file.read_text().splitlines() == ["first"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="The production queue runner uses bash and flock.",
)
def test_runner_works_with_restricted_systemd_path(tmp_path):
    restricted_runner = tmp_path / "argus-run-background-job.sh"
    restricted_runner.write_text(RUNNER.read_text())
    restricted_runner.chmod(0o644)

    result = subprocess.run(
        [
            "bash",
            str(restricted_runner),
            "argus-test-restricted",
            "bash",
            "-c",
            "printf ok",
        ],
        env={
            **os.environ,
            "ARGUS_BACKGROUND_QUEUE_LOCK_FILE": str(tmp_path / "queue.lock"),
            "ARGUS_BACKGROUND_QUEUE_WAIT_SECONDS": "5",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
