# [desc] Regression test verifying /clear uses context_state.notes. [/desc]
"""Regression test: /clear must not crash with AttributeError on context_state."""

import sys
from pathlib import Path

# Add bouzecode source to path
_bz_src = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_bz_src))

from bouzecode.backend.agent.state import AgentState


def test_cmd_clear_no_attribute_error():
    """cmd_clear should work with AgentState.context_state."""
    state = AgentState()
    state.context_state.notes["methodology"] = "some notes"

    config = {"model": "test"}

    # This should NOT raise AttributeError: 'AgentState' object has no attribute 'context_state'
    from bouzecode.backend.commands.core.basic import cmd_clear
    result = cmd_clear("", state, config)
    assert state.context_state.notes == {}
