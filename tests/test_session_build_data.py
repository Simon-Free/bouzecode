# [desc] Regression test verifying _build_session_data accesses state.context_state.notes without AttributeError. [/desc]
"""Regression test for AttributeError: 'AgentState' object has no attribute 'context_state'."""

import sys
from pathlib import Path

_bz_src = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_bz_src))

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.session.session import _build_session_data


def test_build_session_data_no_attribute_error():
    """_build_session_data should access state.context_state.notes."""
    state = AgentState()
    state.messages = [{"role": "user", "content": "hello"}]
    # This should NOT raise AttributeError
    data = _build_session_data(state)
    assert "context_state" in data
    assert "notes" in data["context_state"]
    assert data["context_state"]["notes"] == {}
