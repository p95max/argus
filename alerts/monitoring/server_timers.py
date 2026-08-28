from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess


SYSTEMCTL_BIN = "/usr/bin/systemctl"
SYSTEMCTL_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ServerTimer:
    key: str
    unit: str


@dataclass(frozen=True)
class ServerTimerStatus:
    timer: ServerTimer
    enabled_state: str
    active_state: str
    next_run_at: str = ""
    error: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.enabled_state == "enabled" and self.active_state == "active"


@dataclass(frozen=True)
class ServerTimersStatus:
    timers: tuple[ServerTimerStatus, ...]
    error: str = ""

    @property
    def is_available(self) -> bool:
        return not self.error

    @property
    def is_healthy(self) -> bool:
        return self.is_available and all(timer.is_healthy for timer in self.timers)


SERVER_TIMERS = (
    ServerTimer("gmail", "argus-check-gmail.timer"),
    ServerTimer("unread", "argus-unread-reminders.timer"),
    ServerTimer("cleanup", "argus-cleanup-old-leads.timer"),
    ServerTimer("deploy", "argus-auto-deploy.timer"),
    ServerTimer("backup_local", "argus-backup-db.timer"),
    ServerTimer("backup_remote", "argus-sync-db-to-neon.timer"),
    ServerTimer("health", "argus-health-monitor.timer"),
)


def get_server_timers_status() -> ServerTimersStatus:
    statuses = []
    for timer in SERVER_TIMERS:
        enabled = _run_systemctl(["is-enabled", timer.unit])
        if _is_systemd_unavailable(enabled):
            return ServerTimersStatus((), error=enabled.stderr or "systemctl is unavailable")

        active = _run_systemctl(["is-active", timer.unit])
        properties = _run_systemctl(
            ["show", timer.unit, "--property=NextElapseUSecRealtime"]
        )
        unavailable_result = _find_systemd_unavailable(enabled, active, properties)
        if unavailable_result:
            return ServerTimersStatus(
                (),
                error=unavailable_result.stderr
                or unavailable_result.stdout
                or "systemctl is unavailable",
            )
        next_run_at = _parse_properties(properties.stdout).get("NextElapseUSecRealtime", "")
        if not next_run_at:
            listed_timers = _run_systemctl(["list-timers", "--all", "--no-legend", "--no-pager"])
            if _is_systemd_unavailable(listed_timers):
                return ServerTimersStatus(
                    (),
                    error=listed_timers.stderr
                    or listed_timers.stdout
                    or "systemctl is unavailable",
                )
            if listed_timers.returncode == 0:
                next_run_at = _timer_line(listed_timers.stdout, timer.unit)
        errors = [
            result.stderr or result.stdout
            for result, allowed_codes in (
                (enabled, {0, 1}),
                (active, {0, 3}),
                (properties, {0}),
            )
            if result.returncode not in allowed_codes
        ]
        statuses.append(
            ServerTimerStatus(
                timer=timer,
                enabled_state=_normalize_state(enabled.stdout, fallback="unknown"),
                active_state=_normalize_state(active.stdout, fallback="unknown"),
                next_run_at=_format_next_run(next_run_at),
                error="; ".join(error for error in errors if error),
            )
        )

    return ServerTimersStatus(tuple(statuses))


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


def _format_next_run(value: str) -> str:
    if not value or value.lower() in {"n/a", "0", "infinity"}:
        return ""

    match = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", value)
    return match.group(1) if match else value


def _timer_line(output: str, unit: str) -> str:
    for line in output.splitlines():
        if unit in line:
            return line.strip()
    return ""
