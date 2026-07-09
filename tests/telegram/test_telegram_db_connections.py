import pytest

from alerts.telegram import handlers


def test_run_with_fresh_db_connection_closes_before_and_after(monkeypatch):
    calls = []

    monkeypatch.setattr(handlers, "close_old_connections", lambda: calls.append("close"))

    def build_message():
        calls.append("build")
        return "ok"

    assert handlers._run_with_fresh_db_connection(build_message) == "ok"
    assert calls == ["close", "build", "close"]


def test_run_with_fresh_db_connection_closes_after_exception(monkeypatch):
    calls = []

    monkeypatch.setattr(handlers, "close_old_connections", lambda: calls.append("close"))

    def broken_builder():
        calls.append("build")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        handlers._run_with_fresh_db_connection(broken_builder)

    assert calls == ["close", "build", "close"]
