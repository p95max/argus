from alerts import server_timers


def test_server_timer_status_uses_list_timers_when_next_property_is_empty(monkeypatch):
    responses = iter(
        [
            server_timers.CommandResult(0, "enabled", ""),
            server_timers.CommandResult(0, "active", ""),
            server_timers.CommandResult(0, "NextElapseUSecRealtime=", ""),
            server_timers.CommandResult(
                0,
                "Thu 2026-07-23 12:50:00 CEST 2min left Thu 2026-07-23 12:45:00 CEST argus-check-gmail.timer",
                "",
            ),
        ]
    )
    monkeypatch.setattr(server_timers, "SERVER_TIMERS", (server_timers.SERVER_TIMERS[0],))
    calls = []

    def run_systemctl(args):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(server_timers, "_run_systemctl", run_systemctl)

    status = server_timers.get_server_timers_status()

    assert status.is_healthy is True
    assert status.timers[0].next_run_at == "12:50:00"
    assert calls[-1] == ["list-timers", "--all", "--no-legend", "--no-pager"]
