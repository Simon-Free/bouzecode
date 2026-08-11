# [desc] Verrou : /telegram est atteignable via handle_slash et visible dans /help. [/desc]
"""`/telegram` must be reachable, not merely implemented.

`cmd_telegram` was imported by `dispatcher.py` and never put in `COMMANDS`, so
typing `/telegram` printed "Unknown command". Importing a handler is not wiring
it. These tests therefore go through `handle_slash` — the same entry point the
REPL uses — rather than reading the table, which would prove nothing.

No network and no polling thread: the two arg shapes exercised here return
before `_tg_api` is ever called.
"""
from __future__ import annotations

import threading

import pytest

from bouzecode.backend.commands import telegram_cmd
from bouzecode.backend.commands.dispatcher import COMMANDS, _CMD_META, handle_slash


class _State:
    """Stand-in for the REPL session state; the bridge only stores it on config."""

    def __init__(self) -> None:
        self.messages: list[dict] = []


@pytest.fixture
def state():
    return _State()


@pytest.fixture
def config():
    return {"telegram_token": "", "telegram_chat_id": 0}


@pytest.fixture(autouse=True)
def _no_bridge_left_behind():
    """The bridge globals are process state — reset them around each test."""
    telegram_cmd._telegram_thread = None
    telegram_cmd._telegram_stop = threading.Event()
    yield
    telegram_cmd._telegram_thread = None


def test_slash_telegram_status_runs_the_real_command(capsys, state, config):
    """`/telegram status` reaches `cmd_telegram` and reports the unconfigured state."""
    handled = handle_slash("/telegram status", state, config)

    assert handled is True
    out = capsys.readouterr().out
    assert "Not configured" in out
    assert "Unknown command" not in out


def test_slash_telegram_status_sees_a_saved_configuration(capsys, state):
    """The dispatcher passes the live config through, not a copy of an empty one."""
    config = {"telegram_token": "a-token", "telegram_chat_id": 4242}

    handle_slash("/telegram status", state, config)

    assert "Configured but not running" in capsys.readouterr().out


def test_slash_telegram_forwards_its_arguments(capsys, state, config):
    """The text after the command name reaches the handler and is parsed there."""
    handle_slash("/telegram a-token not-a-number", state, config)

    assert "Chat ID must be a number" in capsys.readouterr().err
    # Rejected before anything was persisted.
    assert config["telegram_token"] == ""


def test_slash_telegram_stop_reports_no_running_bridge(capsys, state, config):
    handle_slash("/telegram stop", state, config)

    assert "not running" in capsys.readouterr().out


def test_help_lists_telegram(capsys, state, config):
    """`/help` prints `_CMD_META`, so a wired command must appear there."""
    handle_slash("/help", state, config)

    out = capsys.readouterr().out
    assert "/telegram" in out
    assert "stop | status" in out


def test_every_dispatchable_command_is_documented():
    """The defect class behind this ticket: dispatchable and invisible at once.

    `/timing` was in `COMMANDS` with no `_CMD_META` entry, so `/help` never
    mentioned it. Equality both ways keeps the two tables from drifting again.
    """
    assert sorted(COMMANDS) == sorted(_CMD_META)


def test_telegram_handler_matches_the_dispatcher_calling_convention():
    """`handle_slash` calls `handler(args, state, config)` positionally."""
    import inspect

    parameters = list(inspect.signature(COMMANDS["telegram"]).parameters.values())

    assert len(parameters) == 3
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters)
