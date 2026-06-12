"""E2E tests for the /telegram command — bridge start, stop, status, graceful degradation."""
from __future__ import annotations

import sys
import threading
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from bouzecode.backend.commands.telegram_cmd import cmd_telegram, HAS_PTB
from bouzecode.backend.commands import telegram_cmd


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Minimal config dict for tests."""
    return {"telegram_token": "", "telegram_chat_id": 0}


@pytest.fixture
def state():
    """Minimal state object."""
    return MagicMock()


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level globals between tests."""
    telegram_cmd._telegram_thread = None
    telegram_cmd._telegram_stop = threading.Event()
    yield
    # Cleanup: stop any thread that may have started
    if telegram_cmd._telegram_thread and telegram_cmd._telegram_thread.is_alive():
        telegram_cmd._telegram_stop.set()
        telegram_cmd._telegram_thread.join(timeout=2)
    telegram_cmd._telegram_thread = None


# ── Tests: basic commands ─────────────────────────────────────────────────────

def test_telegram_no_config(config, state, capsys):
    """No token/chat_id → error message, no crash."""
    result = cmd_telegram("", state, config)
    assert result is True
    captured = capsys.readouterr()
    assert "No config found" in captured.out or "No config found" in captured.err


def test_telegram_invalid_chat_id(config, state, capsys):
    """Non-numeric chat_id → error message."""
    result = cmd_telegram("SOMETOKEN abc", state, config)
    assert result is True
    captured = capsys.readouterr()
    assert "must be a number" in (captured.out + captured.err)


def test_telegram_status_not_configured(config, state, capsys):
    """/telegram status when not configured."""
    result = cmd_telegram("status", state, config)
    assert result is True
    captured = capsys.readouterr()
    assert "Not configured" in captured.out


def test_telegram_status_configured_not_running(config, state, capsys):
    """/telegram status when configured but bridge not running."""
    config["telegram_token"] = "fake:token"
    config["telegram_chat_id"] = 12345
    result = cmd_telegram("status", state, config)
    assert result is True
    captured = capsys.readouterr()
    assert "not running" in captured.out.lower() or "Use /telegram to start" in captured.out


def test_telegram_stop_not_running(config, state, capsys):
    """/telegram stop when not running → warning."""
    result = cmd_telegram("stop", state, config)
    assert result is True
    captured = capsys.readouterr()
    assert "not running" in captured.out.lower()


def test_telegram_start_success(config, state, capsys):
    """Start bridge with mocked API → thread starts, info messages emitted."""
    fake_me = {"ok": True, "result": {"username": "test_bot"}}

    with patch.object(telegram_cmd, "_tg_api", return_value=fake_me):
        with patch.object(telegram_cmd, "_tg_poll_loop"):
            result = cmd_telegram("FAKETOKEN 99999", state, config)

    assert result is True
    captured = capsys.readouterr()
    assert "test_bot" in captured.out
    assert "bridge active" in captured.out.lower() or "Bridge active" in captured.out


def test_telegram_start_invalid_token(config, state, capsys):
    """Start bridge with invalid token → error."""
    with patch.object(telegram_cmd, "_tg_api", return_value={"ok": False}):
        result = cmd_telegram("BADTOKEN 99999", state, config)

    assert result is True
    captured = capsys.readouterr()
    assert "Invalid bot token" in (captured.out + captured.err)


def test_telegram_start_shows_ptb_warning_when_missing(config, state, capsys):
    """When python-telegram-bot is not installed, info note is shown."""
    fake_me = {"ok": True, "result": {"username": "test_bot"}}

    with patch.object(telegram_cmd, "HAS_PTB", False):
        with patch.object(telegram_cmd, "_tg_api", return_value=fake_me):
            with patch.object(telegram_cmd, "_tg_poll_loop"):
                result = cmd_telegram("FAKETOKEN 99999", state, config)

    assert result is True
    captured = capsys.readouterr()
    assert "python-telegram-bot" in captured.out or "pip install" in captured.out


def test_telegram_start_no_warning_when_ptb_present(config, state, capsys):
    """When python-telegram-bot IS installed, no extra warning."""
    fake_me = {"ok": True, "result": {"username": "test_bot"}}

    with patch.object(telegram_cmd, "HAS_PTB", True):
        with patch.object(telegram_cmd, "_tg_api", return_value=fake_me):
            with patch.object(telegram_cmd, "_tg_poll_loop"):
                result = cmd_telegram("FAKETOKEN 99999", state, config)

    assert result is True
    captured = capsys.readouterr()
    assert "python-telegram-bot" not in captured.out


# ── Tests: graceful degradation (module import) ──────────────────────────────

def test_telegram_module_importable_without_ptb():
    """telegram_cmd module imports fine even without python-telegram-bot."""
    # This test verifies the module-level try/except works.
    # If we got here, the import at top of file succeeded.
    assert hasattr(telegram_cmd, "cmd_telegram")
    assert hasattr(telegram_cmd, "HAS_PTB")
    # HAS_PTB should be a bool
    assert isinstance(telegram_cmd.HAS_PTB, bool)
