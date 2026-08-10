# [desc] Reproduces bug where plan validation IPC status gets overwritten by awaiting_input [/desc]
"""Reproduce bug: plan validation status overwritten by awaiting_input."""
import json
from pathlib import Path


import pytest


@pytest.fixture
def ipc_dir(tmp_path, monkeypatch):
    """Create a temporary IPC dir and point the env var at it (auto-restored)."""
    d = tmp_path / "ipc"
    d.mkdir()
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(d))
    return d


def _read_ipc_status(ipc_dir: Path) -> str:
    state_file = ipc_dir / "state.json"
    if not state_file.exists():
        return ""
    return json.loads(state_file.read_text(encoding="utf-8")).get("status", "")


def _write_ipc_state(ipc_dir: Path, status: str, **extra):
    payload = {"status": status, "updated_at": 0, **extra}
    (ipc_dir / "state.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class TestPersistPauseRespectsIsplanValidation:
    """_persist_pause_and_exit must write awaiting_plan_validation when is_plan_validation=True."""

    def test_writes_plan_validation_status(self, ipc_dir):
        """PausedForInput with is_plan_validation=True should write
        awaiting_plan_validation, not awaiting_input."""
        from bouzecode.ui.repl import _persist_pause_and_exit
        from bouzecode.backend.tools.interaction import PausedForInput

        pause = PausedForInput(
            question="Valides-tu ce plan ?",
            options=[{"label": "Oui", "description": "Approuver"}],
            allow_freetext=True,
            is_plan_validation=True,
        )

        state = type("S", (), {"messages": [], "turn_count": 1})()
        config = {"_session_file": None}

        with pytest.raises(SystemExit):
            _persist_pause_and_exit(pause, state, config)

        assert _read_ipc_status(ipc_dir) == "awaiting_plan_validation"

    def test_writes_awaiting_input_for_normal_question(self, ipc_dir):
        """Normal PausedForInput (not plan validation) should still write awaiting_input."""
        from bouzecode.ui.repl import _persist_pause_and_exit
        from bouzecode.backend.tools.interaction import PausedForInput

        pause = PausedForInput(
            question="Quelle branche ?",
            options=[],
            allow_freetext=True,
            is_plan_validation=False,
        )

        state = type("S", (), {"messages": [], "turn_count": 1})()
        config = {"_session_file": None}

        with pytest.raises(SystemExit):
            _persist_pause_and_exit(pause, state, config)

        assert _read_ipc_status(ipc_dir) == "awaiting_input"
