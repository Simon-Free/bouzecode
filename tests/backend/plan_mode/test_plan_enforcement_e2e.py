# [desc] Tests that WritePlan is advisory (not enforced) and Write/Edit run without a prior plan
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that WritePlan is advisory (not enforced) and Write/Edit run without a prior plan</param></tool_use> [/desc]
"""WritePlan contract observed through real bouzecode() conversations.

The hard plan gate is GONE by design (registration.py: 'Plan check disabled —
WritePlan is advisory, not enforced'; the V2 prompt allows WritePlan + edits in
the same turn). These tests pin the advisory contract: Write/Edit run without a
plan, WritePlan still records the plan and appends a '## Plan @' block to the
methodology note.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
APPROVE = {"_plan_auto_validate_result": (True, "")}


def _write(path, tid="w1", content="data"):
    return (f'<tool_use name="Write" id="{tid}"><param name="file_path">{path}</param>'
            f'<param name="content">{content}</param></tool_use>')


def _writeplan(tid="p1"):
    return ('<tool_use name="WritePlan" id="' + tid + '"><param name="content">'
            '# Plan\n## Tests\nwrite a failing test first</param></tool_use>')


def _tool_results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


@pytest.fixture(autouse=True)
def _clean_plans():
    yield
    shutil.rmtree(Path.cwd() / ".nano_claude" / "plans", ignore_errors=True)


# ── advisory: writes run without a plan ──────────────────────────────────────

def test_write_without_plan_is_allowed_advisory_contract(tmp_path):
    """WritePlan is advisory: a Write on a regular source file runs without any
    prior plan (the old hard 'PLAN REQUIRED' gate is gone by design)."""
    f = tmp_path / "server.py"
    mock = MockLLM([f"{METH}\n{_write(f)}", f"done.\n{METH}"])
    result = bouzecode(["write the server"], mock_llm=mock)
    out = _tool_results(result, "Write")[0]
    assert "PLAN REQUIRED" not in out
    assert f.exists()


# ── WritePlan records + appends a Plan block ─────────────────────────────────

def test_writeplan_then_write_is_allowed(tmp_path):
    f = tmp_path / "feature.py"
    mock = MockLLM([
        f"{METH}\n{_writeplan()}",
        f"{METH}\n{_write(f, 'w2')}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["plan then build"], mock_llm=mock, config_overrides=APPROVE)
    assert "Plan saved" in _tool_results(result, "WritePlan")[0]
    write_out = _tool_results(result, "Write")[0]
    assert "PLAN REQUIRED" not in write_out
    assert f.exists()  # write succeeded after the plan was recorded


def test_writeplan_appends_plan_block_to_methodology(tmp_path):
    mock = MockLLM([f"{METH}\n{_writeplan()}", f"done.\n{METH}"])
    result = bouzecode(["plan it"], mock_llm=mock, config_overrides=APPROVE)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "## Plan @" in note
    assert "write a failing test first" in note


def test_read_is_never_plan_gated(tmp_path):
    f = tmp_path / "anything.py"
    f.write_text("line1\nline2\n", encoding="utf-8")
    snippet = (f'<tool_use name="Snippet" id="s1"><param name="file_path">{f}</param>'
               f'<param name="discard">true</param></tool_use>')
    mock = MockLLM([
        f'{METH}\n<tool_use name="Read" id="r1"><param name="file_path">{f}</param></tool_use>',
        f"done.\n{METH}\n{snippet}",
    ])
    result = bouzecode(["read it"], mock_llm=mock)
    read_out = _tool_results(result, "Read")[0]
    assert "PLAN REQUIRED" not in read_out
    assert "line1" in read_out
