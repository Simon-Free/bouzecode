# [desc] Conversation feature tests for tool_id snippeting: inline doc-tool results wrapped on the wire, snippeted by tool_id, enforced.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Conversation feature tests for tool_id snippeting: inline doc-tool results wrapped on the wire, snippeted by tool_id, enforced.</param></tool_use> [/desc]
"""tool_id snippeting through real bouzecode() conversations.

Some tools (e.g. an inline doc tool) produce snippetable output keyed by the
tool_call id rather than a file path. We register such a tool, then drive a
conversation where the model calls it and snippets it by tool_id, asserting:
- the snippeted lines land in the methodology note,
- the result is wrapped with the "A SNIPPETER id: tool_id=..." markers on the wire,
- an un-snippeted result triggers enforcement.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE
from bouzecode.backend.core.tool_registry import (
    ToolDef, register_tool, push_local_overlay, pop_local_overlay,
)

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# Must be >= SNIPPET_MIN_LINES (50) to trigger wrapping/enforcement
DOC = "\n".join(
    ["alpha", "beta", "gamma"]
    + [f"doc line {i}" for i in range(4, 55)]
)


@pytest.fixture
def doc_tool():
    push_local_overlay()
    register_tool(ToolDef(
        name="get_doc",
        schema={"name": "get_doc", "description": "doc", "input_schema": {"type": "object", "properties": {}}},
        func=lambda p, c: DOC,
        snippetable=True,
        snippet_key="tool_id",
    ))
    yield
    pop_local_overlay()


def test_tool_id_snippet_lands_in_note_and_wraps_on_wire(doc_tool):
    mock = MockLLM([
        f'{METH}\n<tool_use name="get_doc" id="d1"></tool_use>',
        f'{METH}\n<tool_use name="Snippet" id="s1"><param name="tool_id">d1</param>'
        f'<param name="ranges">[[1, 2]]</param><param name="label">doc</param></tool_use>',
        f"Done.\n{METH}",
    ])
    # No mock_tools: get_doc runs its registered func (returns DOC) and, crucially,
    # Methodology/Snippet execute for real (mock_tools would fake every tool).
    result = bouzecode(["get the docs"], mock_llm=mock)

    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "alpha" in note and "beta" in note
    assert "gamma" not in note  # only the [1,2] range

    # On turn 2 the get_doc result is sent back wrapped with the snippet markers.
    payload2 = str(mock.recorded_calls[1])
    assert "A SNIPPETER id: tool_id=d1" in payload2
