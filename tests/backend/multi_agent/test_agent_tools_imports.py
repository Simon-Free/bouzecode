# [desc] Regression: ListAgentTypes and the agent-spawn path resolve their imports (no NameError). [/desc]
"""Regression for the live failure `Error executing ListAgentTypes: name
'load_agent_definitions' is not defined` — multi_agent/tools.py used
load_agent_definitions / get_agent_definition / SubAgentManager without importing them.
"""
import pytest

from bouzecode.backend.multi_agent.tools import _list_agent_types, get_agent_manager
from bouzecode.backend.profiles import resolve_agent_profile
from bouzecode.backend.core import tool_registry
from bouzecode.backend.core.tool_registry import is_enabled, disable_tool
from bouzecode.ui.cli import apply_profile_tools


@pytest.fixture
def restore_tool_state():
    """Snapshot the global disabled-tool set and restore it after the test, so
    profile-whitelist tests (which disable Edit/Write globally) don't leak state
    into the rest of the suite."""
    saved = set(tool_registry._disabled)
    yield
    tool_registry._disabled.clear()
    tool_registry._disabled.update(saved)


def test_list_agent_types_does_not_nameerror():
    out = _list_agent_types({}, {})
    assert isinstance(out, str)
    assert "not defined" not in out  # the old NameError surfaced as a tool result
    # System agents are always listed.
    assert "general-purpose" in out and "meta-agent" in out


def test_list_agent_types_lists_expected_typologies():
    """ListAgentTypes must return a non-empty list including the core typologies, sourced
    from the same service as GET /api/typologies (web_v2.services.typologies)."""
    out = _list_agent_types({}, {})
    for expected in ("manager", "meta-agent", "general-purpose"):
        assert expected in out, f"{expected} missing from ListAgentTypes output"


def test_profile_reenables_declared_dispatch_tools(restore_tool_state):
    """Runtime gate regression: tools/registration.py disables optional tools via the
    `_DEFAULT_ENABLED` whitelist, so Agent / ListAgentTypes are off by default. A
    top-level `--profile manager` agent (web_v2 subprocess) must re-enable the tools it
    declares — otherwise the manager cannot dispatch sub-agents nor list typologies."""
    # Reproduce the gate: the whitelist leaves these disabled at import.
    disable_tool("Agent")
    disable_tool("ListAgentTypes")
    assert not is_enabled("Agent")
    assert not is_enabled("ListAgentTypes")
    # Applying the manager profile (as cli.py does on --profile) re-enables them.
    apply_profile_tools("manager")
    assert is_enabled("Agent")
    assert is_enabled("ListAgentTypes")


def test_manager_profile_tools_are_a_whitelist(restore_tool_state):
    """The manager profile is READ-ONLY: its `tools` list whitelists work tools, so
    applying it must DISABLE Edit/Write (forcing delegation via Agent) while keeping
    its declared work tools and the always-on framework tools enabled. Data-driven from
    the profile so it never drifts from manager.yaml (which the human edits separately)."""
    profile = resolve_agent_profile("manager")
    declared = set(profile.tools)
    apply_profile_tools("manager")
    # Every tool the manager actually declares is enabled.
    for tool in declared:
        assert is_enabled(tool), f"{tool} declared by manager must be enabled"
    # Framework tools can never be stripped by a whitelist.
    for framework in ("Methodology", "FinalAnswer", "Skill", "TaskList"):
        assert is_enabled(framework), f"framework tool {framework} must stay on"
    # Edit/Write are neither framework nor (for a read-only manager) declared → disabled.
    for name in ("Edit", "Write"):
        if name not in declared:
            assert not is_enabled(name), f"{name} must be disabled for read-only manager"


def test_general_purpose_profile_keeps_edit_write(restore_tool_state):
    """An empty `tools` list (general-purpose) means no restriction: Edit/Write stay on."""
    apply_profile_tools("general-purpose")
    assert is_enabled("Edit")
    assert is_enabled("Write")


def test_get_agent_manager_resolves():
    mgr = get_agent_manager()
    assert mgr is not None


def test_resolve_agent_profile_unknown_is_none():
    # The Agent spawn path resolves the profile by name; unknown => None, not NameError.
    assert resolve_agent_profile("___no_such_agent___") is None


def test_resolve_agent_profile_finds_system_agents():
    assert resolve_agent_profile("manager") is not None
    assert resolve_agent_profile("meta-agent").kind == "system"
