import asyncio
import subprocess
from types import SimpleNamespace

from telegram.error import BadRequest

from alerts.telegram import handlers


class FakeTelegramMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeUpdate:
    def __init__(self, chat_id="42", user_id="100"):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_message = FakeTelegramMessage()


class FakeContext:
    def __init__(self):
        self.application = SimpleNamespace(bot_data={"argus_started_at": "started"})


class FakeCallbackQuery:
    def __init__(self, data="alert:1:status", chat_id="42", user_id="100"):
        self.data = data
        self.message = SimpleNamespace(chat_id=chat_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, text, show_alert=False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


class BrokenCallbackQuery(FakeCallbackQuery):
    def __init__(self, *args, answer_error=None, edit_error=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.answer_error = answer_error
        self.edit_error = edit_error

    async def answer(self, text, show_alert=False):
        if self.answer_error:
            raise BadRequest(self.answer_error)
        await super().answer(text, show_alert=show_alert)

    async def edit_message_text(self, **kwargs):
        if self.edit_error:
            raise BadRequest(self.edit_error)
        await super().edit_message_text(**kwargs)


class FakeCallbackUpdate:
    def __init__(self, query):
        self.callback_query = query


def test_daily_summary_command_rejects_unknown_chat(monkeypatch):
    update = FakeUpdate(chat_id="99")
    monkeypatch.setattr(handlers, "is_allowed_update", lambda update: False)

    asyncio.run(handlers.handle_daily_summary_command(update, context=object()))

    assert update.effective_message.replies == [
        {"text": "Этот пользователь или чат не имеет доступа к Argus."}
    ]


def test_daily_summary_command_replies_with_html(monkeypatch):
    update = FakeUpdate()
    monkeypatch.setattr(handlers, "is_allowed_update", lambda update: True)

    async def fake_run_db_sync(func, *args, **kwargs):
        assert func is handlers.build_daily_summary_message
        return "<b>Summary</b>"

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)

    asyncio.run(handlers.handle_daily_summary_command(update, context=object()))

    assert update.effective_message.replies == [
        {
            "text": "<b>Summary</b>",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ]


def test_health_command_passes_bot_started_at_to_builder(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(handlers, "is_allowed_update", lambda update: True)

    async def fake_run_db_sync(func, *args, **kwargs):
        assert func is handlers.build_health_message
        assert kwargs == {"bot_started_at": "started"}
        return "<b>Health</b>"

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)

    asyncio.run(handlers.handle_health_command(update, context=context))

    assert update.effective_message.replies[0]["text"] == "<b>Health</b>"
    assert update.effective_message.replies[0]["parse_mode"] == "HTML"


def test_unread_command_replies_with_html(monkeypatch):
    update = FakeUpdate()
    monkeypatch.setattr(handlers, "is_allowed_update", lambda update: True)

    async def fake_run_db_sync(func, *args, **kwargs):
        assert func is handlers.build_unread_command_message
        return "<b>Unread</b>"

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)

    asyncio.run(handlers.handle_unread_command(update, context=object()))

    assert update.effective_message.replies[0]["text"] == "<b>Unread</b>"
    assert update.effective_message.replies[0]["parse_mode"] == "HTML"


def test_doctor_command_rejects_unknown_chat(monkeypatch):
    update = FakeUpdate(chat_id="99")
    monkeypatch.setattr(handlers, "is_allowed_update", lambda update: False)

    asyncio.run(handlers.handle_doctor_command(update, context=object()))

    assert update.effective_message.replies == [
        {"text": "Этот пользователь или чат не имеет доступа к Argus."}
    ]


def test_doctor_command_replies_with_html(monkeypatch):
    update = FakeUpdate()
    monkeypatch.setattr(handlers, "is_allowed_update", lambda update: True)
    monkeypatch.setattr(handlers, "build_doctor_script_message", lambda: "<b>Doctor</b>")

    asyncio.run(handlers.handle_doctor_command(update, context=object()))

    assert update.effective_message.replies == [
        {
            "text": "<b>Doctor</b>",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ]


def test_alert_callback_without_query_is_ignored():
    asyncio.run(handlers.handle_alert_callback(FakeCallbackUpdate(query=None), context=object()))


def test_alert_callback_answers_permission_error(monkeypatch):
    query = FakeCallbackQuery(data="alert:1:ignored")

    async def fake_run_db_sync(func, *args, **kwargs):
        raise PermissionError

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)

    asyncio.run(handlers.handle_alert_callback(FakeCallbackUpdate(query), context=object()))

    assert query.answers == [
        {
            "text": "Этот пользователь или чат не имеет доступа к Argus.",
            "show_alert": True,
        }
    ]


def test_alert_callback_answers_value_error(monkeypatch):
    query = FakeCallbackQuery(data="bad")

    async def fake_run_db_sync(func, *args, **kwargs):
        raise ValueError("Telegram alert was not found.")

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)

    asyncio.run(handlers.handle_alert_callback(FakeCallbackUpdate(query), context=object()))

    assert query.answers == [
        {"text": "Telegram alert was not found.", "show_alert": True}
    ]


def test_alert_callback_status_check_answers_without_edit(monkeypatch):
    query = FakeCallbackQuery(data="alert:1:status")
    alert = SimpleNamespace(id=1, alert_status="unread")

    async def fake_run_db_sync(func, *args, **kwargs):
        return handlers.AlertCallbackResult(
            alert=alert,
            answer_text="Status: unread",
            status_changed=False,
        )

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)

    asyncio.run(handlers.handle_alert_callback(FakeCallbackUpdate(query), context=object()))

    assert query.answers == [{"text": "Status: unread", "show_alert": True}]
    assert query.edits == []


def test_alert_callback_status_change_answers_and_edits(monkeypatch):
    query = FakeCallbackQuery(data="alert:1:in_work")
    alert = SimpleNamespace(id=1, alert_status="in_work")
    edited = []

    async def fake_run_db_sync(func, *args, **kwargs):
        return handlers.AlertCallbackResult(
            alert=alert,
            answer_text="Status: in work",
            status_changed=True,
        )

    async def fake_safe_edit_alert_message(query_arg, alert_arg):
        edited.append((query_arg, alert_arg))

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)
    monkeypatch.setattr(handlers, "_safe_edit_alert_message", fake_safe_edit_alert_message)

    asyncio.run(handlers.handle_alert_callback(FakeCallbackUpdate(query), context=object()))

    assert query.answers == [{"text": "Status: in work", "show_alert": False}]
    assert edited == [(query, alert)]


def test_safe_answer_callback_ignores_old_or_invalid_query():
    query = BrokenCallbackQuery(answer_error="Query is too old")

    asyncio.run(handlers._safe_answer_callback(query, "too late"))

    assert query.answers == []


def test_safe_edit_alert_message_sends_new_text(monkeypatch):
    query = FakeCallbackQuery()
    alert = SimpleNamespace(id=7)

    async def fake_run_db_sync(func, *args, **kwargs):
        assert func is handlers.build_alert_message
        assert args == (alert,)
        return "<b>Alert</b>"

    monkeypatch.setattr(handlers, "_run_db_sync", fake_run_db_sync)
    monkeypatch.setattr(handlers, "build_alert_keyboard", lambda alert: "keyboard")

    asyncio.run(handlers._safe_edit_alert_message(query, alert))

    assert query.edits == [
        {
            "text": "<b>Alert</b>",
            "parse_mode": "HTML",
            "reply_markup": "keyboard",
            "disable_web_page_preview": True,
        }
    ]


def test_safe_edit_alert_message_ignores_not_modified(monkeypatch):
    query = BrokenCallbackQuery(edit_error="Message is not modified")
    alert = SimpleNamespace(id=7)
    monkeypatch.setattr(handlers, "_run_db_sync", lambda *args, **kwargs: "<b>Alert</b>")

    asyncio.run(handlers._safe_edit_alert_message(query, alert))

    assert query.edits == []


def test_safe_edit_alert_message_ignores_old_query(monkeypatch):
    query = BrokenCallbackQuery(edit_error="Query is too old")
    alert = SimpleNamespace(id=7)
    monkeypatch.setattr(handlers, "_run_db_sync", lambda *args, **kwargs: "<b>Alert</b>")

    asyncio.run(handlers._safe_edit_alert_message(query, alert))

    assert query.edits == []


def test_build_doctor_script_message_handles_missing_script(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(handlers.subprocess, "run", fake_run)

    assert "/usr/local/bin/argus-doctor.sh not found" in handlers.build_doctor_script_message()


def test_build_doctor_script_message_handles_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="doctor", timeout=25)

    monkeypatch.setattr(handlers.subprocess, "run", fake_run)

    assert "Doctor check timed out after 25 seconds" in handlers.build_doctor_script_message()


def test_build_doctor_script_message_includes_git_status_and_failure_icon(monkeypatch):
    monkeypatch.setattr(
        handlers.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="failed <bad>"),
    )
    monkeypatch.setattr(handlers, "build_git_deploy_status_text_v2", lambda: "git ok")

    message = handlers.build_doctor_script_message()

    assert message.startswith("🚨 <b>[DEV] Argus doctor</b>")
    assert "failed &lt;bad&gt;" in message
    assert "git ok" in message
