"""E2E tests for the proactive sentinel — watcher loop, cmd_proactive, callback firing."""
from __future__ import annotations

import sys
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from bouzecode.backend.commands.proactive import cmd_proactive, _proactive_watcher_loop


# ── Tests: cmd_proactive ──────────────────────────────────────────────────────

@pytest.fixture
def config():
    return {
        "_proactive_enabled": False,
        "_proactive_interval": 300,
        "_last_interaction_time": time.time(),
    }


@pytest.fixture
def state():
    return MagicMock()


def test_proactive_status_off(config, state, capsys):
    """Default status is OFF."""
    cmd_proactive("", state, config)
    captured = capsys.readouterr()
    assert "OFF" in captured.out


def test_proactive_enable_5m(config, state, capsys):
    """Enable with '5m' sets interval to 300s."""
    cmd_proactive("5m", state, config)
    assert config["_proactive_enabled"] is True
    assert config["_proactive_interval"] == 300
    captured = capsys.readouterr()
    assert "ON" in captured.out


def test_proactive_enable_30s(config, state, capsys):
    """Enable with '30s' sets interval to 30s."""
    cmd_proactive("30s", state, config)
    assert config["_proactive_enabled"] is True
    assert config["_proactive_interval"] == 30


def test_proactive_enable_1h(config, state, capsys):
    """Enable with '1h' sets interval to 3600s."""
    cmd_proactive("1h", state, config)
    assert config["_proactive_enabled"] is True
    assert config["_proactive_interval"] == 3600


def test_proactive_disable(config, state, capsys):
    """Disable with 'off'."""
    config["_proactive_enabled"] = True
    cmd_proactive("off", state, config)
    assert config["_proactive_enabled"] is False
    captured = capsys.readouterr()
    assert "OFF" in captured.out


def test_proactive_invalid_duration(config, state, capsys):
    """Invalid duration → error, no crash."""
    cmd_proactive("abc", state, config)
    captured = capsys.readouterr()
    assert "Invalid duration" in (captured.out + captured.err)


def test_proactive_status_on(config, state, capsys):
    """Status when enabled."""
    config["_proactive_enabled"] = True
    config["_proactive_interval"] = 60
    cmd_proactive("", state, config)
    captured = capsys.readouterr()
    assert "ON" in captured.out
    assert "60" in captured.out


# ── Tests: _proactive_watcher_loop ───────────────────────────────────────────

def test_proactive_watcher_fires_callback():
    """Watcher loop fires the callback after inactivity interval."""
    callback_called = threading.Event()
    callback_messages = []

    def fake_callback(msg):
        callback_messages.append(msg)
        callback_called.set()

    config = {
        "_proactive_enabled": True,
        "_proactive_interval": 1,  # 1 second for fast test
        "_last_interaction_time": time.time() - 2,  # already past interval
        "_run_query_callback": fake_callback,
    }

    t = threading.Thread(target=_proactive_watcher_loop, args=(config,), daemon=True)
    t.start()

    # Wait for callback to fire (should happen within ~2s)
    fired = callback_called.wait(timeout=5)
    # Stop the loop
    config["_proactive_enabled"] = False
    time.sleep(0.1)

    assert fired, "Proactive callback was not fired within timeout"
    assert len(callback_messages) >= 1
    assert "inactive" in callback_messages[0].lower()


def test_proactive_watcher_does_not_fire_when_disabled():
    """Watcher loop does NOT fire when disabled."""
    callback_called = threading.Event()

    config = {
        "_proactive_enabled": False,
        "_proactive_interval": 1,
        "_last_interaction_time": time.time() - 10,
        "_run_query_callback": lambda msg: callback_called.set(),
    }

    t = threading.Thread(target=_proactive_watcher_loop, args=(config,), daemon=True)
    t.start()

    fired = callback_called.wait(timeout=2)
    config["_proactive_enabled"] = False

    assert not fired, "Callback should NOT fire when proactive is disabled"


def test_proactive_watcher_respects_interval():
    """Watcher does not fire before interval elapses."""
    callback_called = threading.Event()

    config = {
        "_proactive_enabled": True,
        "_proactive_interval": 10,  # 10s — should not fire in 2s
        "_last_interaction_time": time.time(),  # just now
        "_run_query_callback": lambda msg: callback_called.set(),
    }

    t = threading.Thread(target=_proactive_watcher_loop, args=(config,), daemon=True)
    t.start()

    fired = callback_called.wait(timeout=2)
    config["_proactive_enabled"] = False

    assert not fired, "Callback should NOT fire before interval elapses"


def test_proactive_full_flow_with_repl_wiring():
    """Simulate the full REPL wiring: config setup → watcher → callback fires."""
    callback_called = threading.Event()
    query_log = []

    def run_query(msg, is_background=False):
        query_log.append((msg, is_background))
        callback_called.set()

    # Simulate what repl.py does (L199-205 + L515)
    config = {}
    config.setdefault("_proactive_enabled", False)
    config.setdefault("_proactive_interval", 300)
    config.setdefault("_last_interaction_time", time.time())
    config["_run_query_callback"] = lambda msg: run_query(msg, is_background=True)

    # Start watcher thread (as repl does)
    t = threading.Thread(target=_proactive_watcher_loop, args=(config,), daemon=True)
    t.start()

    # Now enable proactive with short interval (as user would via /proactive 1s)
    cmd_proactive("1s", MagicMock(), config)
    # Simulate inactivity by backdating
    config["_last_interaction_time"] = time.time() - 2

    fired = callback_called.wait(timeout=5)
    config["_proactive_enabled"] = False

    assert fired, "Full flow: proactive callback should fire"
    assert len(query_log) >= 1
    assert query_log[0][1] is True  # is_background=True
    assert "inactive" in query_log[0][0].lower()
