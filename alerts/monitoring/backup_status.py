from __future__ import annotations

from dataclasses import dataclass
import subprocess


SYSTEMCTL_BIN = "/usr/bin/systemctl"
SYSTEMCTL_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class BackupJob:
    key: str
    timer_unit: str
    service_unit: str


@dataclass(frozen=True)
class BackupJobStatus:
    job: BackupJob
    enabled_state: str
    active_state: str
    result: str
    last_run_at: str = ""
    error: str = ""

    @property
    def is_healthy(self) -> bool:
        return (
            self.enabled_state == "enabled"
            and self.active_state == "active"
            and self.result == "success"
        )


@dataclass(frozen=True)
class BackupStatus:
    jobs: tuple[BackupJobStatus, ...]
    error: str = ""

    @property
    def is_available(self) -> bool:
        return not self.error

    @property
    def is_healthy(self) -> bool:
        return self.is_available and all(job.is_healthy for job in self.jobs)


BACKUP_JOBS = (
    BackupJob(
        key="local",
        timer_unit="argus-backup-db.timer",
        service_unit="argus-backup-db.service",
    ),
    BackupJob(
        key="remote",
        timer_unit="argus-sync-db-to-neon.timer",
        service_unit="argus-sync-db-to-neon.service",
    ),
)


def get_backup_status() -> BackupStatus:
    statuses = []
    for job in BACKUP_JOBS:
        enabled = _run_systemctl(["is-enabled", job.timer_unit])
        if _is_systemd_unavailable(enabled):
            return BackupStatus((), error=enabled.stderr or "systemctl is unavailable")

        active = _run_systemctl(["is-active", job.timer_unit])
        service = _run_systemctl(
            [
                "show",
                job.service_unit,
                "--property=Result",
                "--property=ExecMainExitTimestamp",
            ]
        )
        unavailable_result = _find_systemd_unavailable(enabled, active, service)
        if unavailable_result:
            return BackupStatus(
                (),
                error=unavailable_result.stderr
                or unavailable_result.stdout
                or "systemctl is unavailable",
            )
        properties = _parse_properties(service.stdout)
        errors = [
            result.stderr or result.stdout
            for result, allowed_codes in (
                (enabled, {0, 1}),
                (active, {0, 3}),
                (service, {0}),
            )
            if result.returncode not in allowed_codes
        ]
        statuses.append(
            BackupJobStatus(
                job=job,
                enabled_state=_normalize_state(enabled.stdout, fallback="unknown"),
                active_state=_normalize_state(active.stdout, fallback="unknown"),
                result=properties.get("Result", "unknown"),
                last_run_at=properties.get("ExecMainExitTimestamp", ""),
                error="; ".join(error for error in errors if error),
            )
        )

    return BackupStatus(tuple(statuses))


def _run_systemctl(args: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            [SYSTEMCTL_BIN, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, exc.stdout or "", exc.stderr or "command timed out")
    except OSError as exc:
        return CommandResult(1, "", str(exc))

    return CommandResult(
        result.returncode,
        (result.stdout or "").strip(),
        (result.stderr or "").strip(),
    )


def _normalize_state(value: str, *, fallback: str) -> str:
    lines = (value or "").strip().splitlines()
    return lines[0].strip() if lines else fallback


def _is_systemd_unavailable(result: CommandResult) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 127 or any(
        marker in text
        for marker in (
            "system has not been booted with systemd",
            "failed to connect to bus",
        )
    )


def _find_systemd_unavailable(*results: CommandResult) -> CommandResult | None:
    return next((result for result in results if _is_systemd_unavailable(result)), None)


def _parse_properties(output: str) -> dict[str, str]:
    properties = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value.strip()
    return properties
