# [desc] E2E tests for the /telegram command: config errors, status, stop, and bridge start against a fake Bot API. [/desc]
"""/telegram behaviour, exercised through `cmd_telegram` itself.

The bridge talks to the Telegram Bot API over plain `urllib` (see
`telegram_cmd._tg_api`) — there is no `python-telegram-bot` dependency and
therefore no `HAS_PTB` flag any more. The two tests that asserted on that flag
were deleted rather than rewritten: they had no subject left.

`_tg_api` / `_tg_poll_loop` are replaced with plain functions through
`monkeypatch` (never `unittest.mock`), so no HTTP request and no polling thread
is created.
"""
from __future__ import annotations

import threading

import pytest

from bouzecode.backend.commands import telegram_cmd
from bouzecode.backend.commands.telegram_cmd import cmd_telegram


class _State:
    """Stand-in for the REPL session state: the bridge only stores it on config."""

    def __init__(self) -> None:
        self.messages: list[dict] = []


@pytest.fixture
def config():
    return {"telegram_token": "", "telegram_chat_id": 0}


@pytest.fixture
def state():
    return _State()


@pytest.fixture(autouse=True)
def _reset_globals():
    """Module-level bridge globals are process state — reset them around each test."""
    telegram_cmd._telegram_thread = None
    telegram_cmd._telegram_stop = threading.Event()
    yield
    if telegram_cmd._telegram_thread and telegram_cmd._telegram_thread.is_alive():
        telegram_cmd._telegram_stop.set()
        telegram_cmd._telegram_thread.join(timeout=2)
    telegram_cmd._telegram_thread = None


@pytest.fixture
def offline_bridge(monkeypatch):
    """Neutralise the two functions that would touch the network / spawn a poller.

    Returns the list of (method, params) the command tried to call, so a test can
    assert on what the bridge asked the API for."""
    calls: list[tuple[str, dict | None]] = []
    replies: dict[str, dict] = {"getMe": {"ok": True, "result": {"username": "test_bot"}}}

    def _fake_api(token, method, params=None):
        calls.append((method, params))
        return replies.get(method, {"ok": True, "result": {}})

    def _fake_poll_loop(token, chat_id, config):
        # The real loop runs until `_telegram_stop` is set; a stub that returns
        # immediately would make the bridge look dead the moment it started.
        telegram_cmd._telegram_stop.wait(5)

    monkeypatch.setattr(telegram_cmd, "_tg_api", _fake_api)
    monkeypatch.setattr(telegram_cmd, "_tg_poll_loop", _fake_poll_loop)
    return calls, replies


def test_telegram_no_config(config, state, capsys):
    """No token/chat_id → error message, no crash."""
    assert cmd_telegram("", state, config) is True
    captured = capsys.readouterr()
    assert "No config found" in captured.out + captured.err


def test_telegram_invalid_chat_id(config, state, capsys):
    """Non-numeric chat_id → error message."""
    assert cmd_telegram("SOMETOKEN abc", state, config) is True
    assert "must be a number" in "".join(capsys.readouterr())


def test_telegram_status_not_configured(config, state, capsys):
    assert cmd_telegram("status", state, config) is True
    assert "Not configured" in capsys.readouterr().out


def test_telegram_status_configured_not_running(config, state, capsys):
    config["telegram_token"] = "fake:token"
    config["telegram_chat_id"] = 12345
    assert cmd_telegram("status", state, config) is True
    out = capsys.readouterr().out
    assert "not running" in out.lower() or "Use /telegram to start" in out


def test_telegram_stop_not_running(config, state, capsys):
    assert cmd_telegram("stop", state, config) is True
    assert "not running" in capsys.readouterr().out.lower()


def test_telegram_start_success(config, state, offline_bridge, capsys):
    """A valid token → getMe is called, the bot name is echoed, the bridge starts."""
    calls, _ = offline_bridge

    assert cmd_telegram("FAKETOKEN 99999", state, config) is True

    out = capsys.readouterr().out
    assert "test_bot" in out
    assert "bridge active" in out.lower()
    assert ("getMe", None) in calls
    assert config["telegram_chat_id"] == 99999
    assert config["_state"] is state


def test_telegram_start_invalid_token(config, state, offline_bridge, capsys):
    """getMe answering ok=false → error, and no bridge thread is created."""
    _, replies = offline_bridge
    replies["getMe"] = {"ok": False}

    assert cmd_telegram("BADTOKEN 99999", state, config) is True

    assert "Invalid bot token" in "".join(capsys.readouterr())
    assert telegram_cmd._telegram_thread is None


def test_telegram_stop_after_start(config, state, offline_bridge, capsys):
    """The bridge started above really is stoppable through /telegram stop."""
    cmd_telegram("FAKETOKEN 99999", state, config)
    capsys.readouterr()

    assert cmd_telegram("stop", state, config) is True
    assert "bridge stopped" in capsys.readouterr().out.lower()
    assert telegram_cmd._telegram_thread is None
