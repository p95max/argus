from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess

from django.utils.translation import gettext as _


GMAIL_TIMER_UNIT = "argus-check-gmail.timer"
GMAIL_SERVICE_UNIT = "argus-check-gmail.service"
SYSTEMCTL_BIN = "/usr/bin/systemctl"
SUDO_BIN = "/usr/bin/sudo"
SYSTEMCTL_TIMEOUT_SECONDS = 8
UNAVAILABLE_STATE = "unavailable"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class GmailPollingStatus:
    enabled_state: str
    active_state: str
    next_run_raw: str = ""
    next_run_label: str = ""
    interval_raw: str = ""
    interval_label: str = ""
    error: str = ""

    @property
    def is_enabled(self) -> bool:
        return self.enabled_state == "enabled"

    @property
    def is_active(self) -> bool:
        return self.active_state == "active"

    @property
    def is_available(self) -> bool:
        return self.enabled_state != UNAVAILABLE_STATE and self.active_state != UNAVAILABLE_STATE

    @property
    def enabled_label(self) -> str:
        if self.enabled_state == UNAVAILABLE_STATE:
            return _("Unavailable")
        return _("Enabled") if self.is_enabled else _("Disabled")

    @property
    def active_label(self) -> str:
        if self.active_state == UNAVAILABLE_STATE:
            return _("unavailable")
        if self.active_state == "active":
            return _("active")
        if self.active_state == "inactive":
            return _("inactive")
        return self.active_state or _("unknown")

    @property
    def localized_next_run_label(self) -> str:
        return _format_next_run(self.next_run_raw) if self.next_run_raw else self.next_run_label

    @property
    def localized_interval_label(self) -> str:
        return _format_interval(self.interval_raw) if self.interval_raw else self.interval_label


class GmailPollingCommandError(RuntimeError):
    pass


def get_gmail_polling_status() -> GmailPollingStatus:
    enabled = _run_systemctl(["is-enabled", GMAIL_TIMER_UNIT])
    if _is_missing_executable(enabled):
        return GmailPollingStatus(
            enabled_state=UNAVAILABLE_STATE,
            active_state=UNAVAILABLE_STATE,
            next_run_label=_("not scheduled"),
            interval_label=_("unknown"),
            error=_("systemctl is not available on this system."),
        )

    active = _run_systemctl(["is-active", GMAIL_TIMER_UNIT])
    props = _run_systemctl(
        [
            "show",
            GMAIL_TIMER_UNIT,
            "--property=NextElapseUSecRealtime",
        ]
    )
    properties = _parse_systemctl_properties(props.stdout)
    next_run_raw = properties.get("NextElapseUSecRealtime", "")
    next_run_label = _format_next_run(next_run_raw)
    if not next_run_raw:
        timers = _run_systemctl(
            ["list-timers", "--all", "--no-legend", "--no-pager", GMAIL_TIMER_UNIT]
        )
        if timers.returncode == 0:
            next_run_raw = timers.stdout
            next_run_label = _format_next_run(timers.stdout)

    timer_definition = _run_systemctl(["cat", GMAIL_TIMER_UNIT])
    interval_raw = _parse_timer_interval(timer_definition.stdout)

    errors = []
    if enabled.returncode not in {0, 1}:
        errors.append(enabled.stderr or enabled.stdout)
    if active.returncode not in {0, 3}:
        errors.append(active.stderr or active.stdout)
    if props.returncode != 0:
        errors.append(props.stderr or props.stdout)

    return GmailPollingStatus(
        enabled_state=_normalize_state(enabled.stdout, fallback="unknown"),
        active_state=_normalize_state(active.stdout, fallback="unknown"),
        next_run_raw=next_run_raw,
        next_run_label=next_run_label,
        interval_raw=interval_raw,
        interval_label=_format_interval(interval_raw),
        error="; ".join(error for error in errors if error),
    )


def enable_gmail_polling() -> None:
    _run_systemctl_action(["enable", "--now", GMAIL_TIMER_UNIT])


def disable_gmail_polling() -> None:
    _run_systemctl_action(["disable", "--now", GMAIL_TIMER_UNIT])


def run_gmail_check_now() -> None:
    _run_systemctl_action(["--no-block", "start", GMAIL_SERVICE_UNIT])


def apply_gmail_polling_action(action: str) -> str:
    if action == "enable":
        enable_gmail_polling()
        return _("Gmail polling enabled.")
    if action == "disable":
        disable_gmail_polling()
        return _("Gmail polling disabled.")
    if action == "run_now":
        run_gmail_check_now()
        return _("Gmail check started.")
    raise ValueError(_("Unknown Gmail polling action."))


def _run_systemctl(args: list[str]) -> CommandResult:
    return _run_command([SYSTEMCTL_BIN, *args])


def _run_systemctl_action(args: list[str]) -> None:
    result = _run_command([SUDO_BIN, "-n", SYSTEMCTL_BIN, *args], timeout=20)
    if result.returncode != 0:
        detail = result.stderr or result.stdout or _("systemctl command failed")
        raise GmailPollingCommandError(detail)


def _run_command(command: list[str], timeout: int = SYSTEMCTL_TIMEOUT_SECONDS) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, exc.stdout or "", exc.stderr or _("command timed out"))
    except OSError as exc:
        return CommandResult(1, "", str(exc))

    return CommandResult(
        result.returncode,
        (result.stdout or "").strip(),
        (result.stderr or "").strip(),
    )


def _is_missing_executable(result: CommandResult) -> bool:
    return result.returncode == 127


def _normalize_state(value: str, *, fallback: str) -> str:
    first_line = (value or "").strip().splitlines()
    return first_line[0].strip() if first_line else fallback


def _parse_systemctl_properties(output: str) -> dict[str, str]:
    properties = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value.strip()
    return properties


def _parse_timer_interval(output: str) -> str:
    intervals = re.findall(r"^OnUnitActiveSec=(.+)$", output, flags=re.MULTILINE)
    return intervals[-1].strip() if intervals else ""


def _format_next_run(value: str) -> str:
    if not value or value.lower() in {"n/a", "0", "infinity"}:
        return _("not scheduled")

    match = re.search(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\b", value)
    if not match:
        return value
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _format_interval(value: str) -> str:
    if not value:
        return _("unknown")

    match = re.fullmatch(r"(\d+)(min|s|h|d)", value.strip())
    if not match:
        return value

    amount = int(match.group(1))
    unit = match.group(2)
    labels = {
        "s": _("seconds"),
        "min": _("minutes"),
        "h": _("hours"),
        "d": _("days"),
    }
    return _("%(amount)s %(unit)s") % {"amount": amount, "unit": labels[unit]}
