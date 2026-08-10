"""The meta-agent must be able to DELEGATE code work (like the manager) — it declares the
Agent/ListAgentTypes orchestration tools AND keeps its light-editing tools. These tools are
OFF by default (registration._DEFAULT_ENABLED), so the ONLY way the meta-agent gets them is
by declaring them in its profile whitelist. We EXERCISE apply_profile_tools (not just 'the
YAML loads') to prove Agent is actually enabled — the empirical dogfood (a meta-agent spawning
a coder child) is the end-to-end proof this unit test guards against regressing."""
from bouzecode.backend.profiles import resolve_agent_profile


def test_meta_agent_declares_delegation_and_editing_tools():
    tools = set(resolve_agent_profile("meta-agent").tools)
    # light 'méta' editing (recombine skills/profiles itself)
    assert {"Read", "Write", "Edit", "Bash", "Glob", "Grep"} <= tools
    # delegation to a code agent (advanced code editing)
    assert {"Agent", "ListAgentTypes"} <= tools


def test_apply_profile_tools_actually_enables_agent_for_meta_agent():
    import bouzecode.backend.tools.registration  # noqa: F401 — populate registry
    from bouzecode.backend.core import tool_registry as tr
    from bouzecode.ui.cli import apply_profile_tools

    saved = set(tr._disabled)  # global registry state — restore after
    try:
        apply_profile_tools("meta-agent")
        assert tr.is_enabled("Agent"), "Agent not enabled → meta-agent cannot delegate"
        assert tr.is_enabled("ListAgentTypes")
        assert tr.is_enabled("Edit"), "light editing lost"
        assert tr.is_enabled("Methodology"), "framework tool wrongly stripped"
    finally:
        tr._disabled = saved
