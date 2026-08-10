# [desc] Tests: manager subagent_type guard refuses generic types and hides them from ListAgentTypes. [/desc]
"""Tests for the manager subagent_type guard (tools.py).

User-centric: we exercise the REAL public entry points of the Agent tool:
- `_manager_type_guard` (pure decision function),
- `_agent_tool` (the tool func) proving a forbidden type is refused WITHOUT any
  sub-agent being spawned (the return message tells the manager to pick a
  specialized type),
- `_list_agent_types` (the ListAgentTypes tool func) proving the forbidden
  types are hidden from the list a manager sees.

No unittest.mock — plain dict configs; the guard short-circuits before any
thread/worktree is created, so nothing real is spawned.
"""
import pytest

from bouzecode.backend.multi_agent.tools import (
    _manager_type_guard,
    _agent_tool,
    _list_agent_types,
    _MANAGER_FORBIDDEN_TYPES,
)


# --- pure decision function -------------------------------------------------

@pytest.mark.parametrize("forbidden", sorted(_MANAGER_FORBIDDEN_TYPES))
def test_manager_cannot_dispatch_generic_type(forbidden):
    msg = _manager_type_guard({"_agent_type": "manager"}, forbidden)
    assert msg is not None
    # message must be explicit and point toward a specialized type
    assert forbidden in msg
    assert "specialized" in msg.lower() or "spécialis" in msg.lower()


def test_manager_can_dispatch_specialized_type():
    assert _manager_type_guard({"_agent_type": "manager"}, "coder") is None
    assert _manager_type_guard({"_agent_type": "manager"}, "meta-agent") is None


def test_guard_is_case_insensitive():
    assert _manager_type_guard({"_agent_type": "manager"}, "General-Purpose") is not None
    assert _manager_type_guard({"_agent_type": "manager"}, "DEFAULT") is not None


def test_non_manager_may_dispatch_anything():
    # a general-purpose (or unset) caller keeps full freedom
    assert _manager_type_guard({"_agent_type": "general-purpose"}, "general-purpose") is None
    assert _manager_type_guard({}, "default") is None
    assert _manager_type_guard({"_agent_type": "coder"}, "general-purpose") is None


def test_guard_ignores_empty_subagent_type():
    # no explicit type requested → nothing to forbid
    assert _manager_type_guard({"_agent_type": "manager"}, "") is None


# --- tool entry point: refusal happens WITHOUT spawning ---------------------

@pytest.mark.parametrize("forbidden", sorted(_MANAGER_FORBIDDEN_TYPES))
def test_agent_tool_refuses_forbidden_type_without_spawn(forbidden):
    # If the guard did NOT short-circuit, _agent_tool would try to spawn a real
    # sub-agent thread. The guard runs first, so we get a plain refusal string.
    out = _agent_tool(
        {"prompt": "do something", "subagent_type": forbidden},
        {"_agent_type": "manager"},
    )
    assert forbidden in out
    assert "specialized" in out.lower() or "spécialis" in out.lower()


# --- ListAgentTypes hides forbidden types from a manager --------------------

def test_list_agent_types_hides_forbidden_for_manager():
    listing = _list_agent_types({}, {"_agent_type": "manager"})
    # Each typology is rendered as a line "  {name:20s}  {desc}"; assert the
    # forbidden NAME never appears as such an entry. (A substring check would be
    # a false positive: another profile's description text may cite the word.)
    for forbidden in _MANAGER_FORBIDDEN_TYPES:
        assert f"  {forbidden:20s}  " not in listing


def test_list_agent_types_shows_all_for_non_manager():
    listing = _list_agent_types({}, {"_agent_type": "general-purpose"})
    # at least one of the generic types is present for a non-manager caller
    assert "general-purpose" in listing or "default" in listing
