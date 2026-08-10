# [desc] Regression: the agent loop wires config["artifacts"] to state.artifacts so plugin tools can persist. [/desc]
"""Plugin artifact store wiring.

Plugin tools (e.g. a report-builder plugin's create_model) persist into a shared
``config["artifacts"]`` list the host must provide. Before this was wired, the
CLI loop built config without that key and every pbi_* call died with
``KeyError: 'artifacts'``. These tests lock the contract:

  1. AgentState gives each session its own empty artifacts list.
  2. The loop hands tools a config whose ``artifacts`` IS state.artifacts, so a
     write survives on the state (and thus across turns).

The wiring is exercised plugin-independently via a throwaway probe tool, so the
guard holds even where no such plugin is installed.
"""
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.core.tool_registry import (
    ToolDef, register_tool, unregister_tool, enable_tool,
)
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode

METH = '<tool_use name="Methodology" id="m1"><param name="content">test</param></tool_use>'

_SENTINEL = {"tool": "store_pbi_model", "id": "probe", "from": "probe"}


def test_agent_state_artifacts_default_and_isolated():
    """Each AgentState starts with its own empty artifacts list."""
    a, b = AgentState(), AgentState()
    assert a.artifacts == [] and b.artifacts == []
    a.artifacts.append(_SENTINEL)
    assert b.artifacts == [], "artifacts must not be shared across instances"


def test_loop_wires_config_artifacts_to_state():
    """A tool writing to config['artifacts'] mutates state.artifacts."""
    probe = ToolDef(
        name="ArtifactProbe",
        schema={"name": "ArtifactProbe", "description": "test probe",
                "input_schema": {"type": "object", "properties": {}, "required": []}},
        func=lambda p, c: (c["artifacts"].append(dict(_SENTINEL)), "probed")[1],
        read_only=False,
        concurrent_safe=False,
    )
    register_tool(probe)
    enable_tool("ArtifactProbe")
    try:
        mock = MockLLM([
            f'{METH}\n<tool_use name="ArtifactProbe" id="p1"></tool_use>',
            "done.",
        ])
        result = bouzecode(["go"], mock_llm=mock)
        ids = [a.get("id") for a in result.state.artifacts]
        assert "probe" in ids, (
            "tool's config['artifacts'] is not state.artifacts — "
            "loop wiring (config['artifacts'] = state.artifacts) is broken"
        )
    finally:
        unregister_tool("ArtifactProbe")
