# [desc] Conversation feature tests for the advisory WritePlan contract: writes are never plan-gated, temp_/test_ names included, and WritePlan appends a ## Plan block to the methodology note. [/desc]
"""WritePlan contract observed through real bouzecode() conversations.

The hard plan gate is GONE by design (registration.py: WritePlan is advisory,
not enforced; the V2 prompt allows WritePlan + edits in the same turn), and the
auto-validator was removed with it. These tests pin what remains: Write/Edit run
without any prior plan — on regular source files as well as on the historically
exempt `temp_`/`test_` names — and WritePlan still records the plan and appends a
'## Plan @' block to the methodology note the model carries between turns.

Replaces the direct-call unit file test_plan_enforcement.py (deleted with the
gate it tested).
"""
from __future__ import annotations


import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'

# WritePlan is advisory, but it still runs the plan auto-validator — an LLM call.
# `_plan_auto_validate_result` is the production seam that short-circuits it
# (plan_auto_validator.validate_plan_auto reads it first); without it these
# conversations reach the real API and die on a missing key. The verdict itself
# is not what these tests are about — they pin what happens AFTER an approval.
_APPROVED_PLAN = {"_plan_auto_validate_result": (True, "")}


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
def _plans_in_a_private_cwd(tmp_path_factory, monkeypatch):
    """`_write_plan` writes to `<cwd>/.nano_claude/plans/<session>.md`, and the
    session id defaults to "default" — so every plan test writes the SAME path.
    Wiping that shared directory was safe sequentially and destructive under
    `-n auto`: one worker deleted the plan another had just written. Giving each
    test its own cwd removes the shared path instead of racing on it."""
    monkeypatch.chdir(tmp_path_factory.mktemp("plan_cwd"))


# ── advisory: writes run without a plan ──────────────────────────────────────

def test_write_without_plan_is_allowed(tmp_path):
    """The user asks for a source file and gets it: no plan is required first."""
    f = tmp_path / "server.py"
    mock = MockLLM([f"{METH}\n{_write(f)}", "done."])
    result = bouzecode(["write the server"], mock_llm=mock)
    out = _tool_results(result, "Write")[0]
    assert "PLAN REQUIRED" not in out
    assert f.exists()


@pytest.mark.parametrize("name", ["temp_scratch.py", "test_server.py"])
def test_write_to_temp_and_test_files_is_allowed(tmp_path, name):
    """Scratch and test files (temp_*, test_*) are writable without a plan —
    the historical plan-mode exemption still holds now that the gate is gone."""
    f = tmp_path / name
    mock = MockLLM([f"{METH}\n{_write(f)}", "done."])
    result = bouzecode([f"write {name}"], mock_llm=mock)
    assert "PLAN REQUIRED" not in _tool_results(result, "Write")[0]
    assert f.exists()


def test_edit_without_plan_is_allowed(tmp_path):
    """Editing an existing source file needs no plan either."""
    f = tmp_path / "app.py"
    f.write_text("value = 1\n", encoding="utf-8")
    read = f'<tool_use name="Read" id="r1"><param name="file_path">{f}</param></tool_use>'
    discard = (f'<tool_use name="Snippet" id="s1"><param name="file_path">{f}</param>'
               f'<param name="discard">true</param></tool_use>')
    edit = (f'<tool_use name="Edit" id="e1"><param name="file_path">{f}</param>'
            f'<param name="old_string">value = 1</param>'
            f'<param name="new_string">value = 2</param></tool_use>')
    mock = MockLLM([
        f"{METH}\n{read}",
        f"{METH}\n{discard}\n{edit}",
        "done.",
    ])
    result = bouzecode(["bump the value"], mock_llm=mock)
    assert "PLAN REQUIRED" not in _tool_results(result, "Edit")[0]
    assert "value = 2" in f.read_text(encoding="utf-8")


# ── WritePlan records + appends a Plan block ─────────────────────────────────

def test_writeplan_then_write_both_succeed(tmp_path):
    """Planning first still works: the plan is saved and the write goes through."""
    f = tmp_path / "feature.py"
    mock = MockLLM([
        f"{METH}\n{_writeplan()}",
        f"{METH}\n{_write(f, 'w2')}",
        "done.",
    ])
    result = bouzecode(["plan then build"], mock_llm=mock,
                       config_overrides=_APPROVED_PLAN)
    assert "Plan saved" in _tool_results(result, "WritePlan")[0]
    assert "PLAN REQUIRED" not in _tool_results(result, "Write")[0]
    assert f.exists()


def test_writeplan_appends_plan_block_to_methodology(tmp_path):
    """A written plan is carried forward in the methodology note as a '## Plan @' block."""
    mock = MockLLM([f"{METH}\n{_writeplan()}", "done."])
    result = bouzecode(["plan it"], mock_llm=mock, config_overrides=_APPROVED_PLAN)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "## Plan @" in note
    assert "write a failing test first" in note


def test_empty_plan_is_rejected(tmp_path):
    """An empty plan is refused instead of being silently recorded."""
    empty = ('<tool_use name="WritePlan" id="p1">'
             '<param name="content">   </param></tool_use>')
    mock = MockLLM([f"{METH}\n{empty}", "done."])
    result = bouzecode(["plan nothing"], mock_llm=mock)
    assert "empty" in _tool_results(result, "WritePlan")[0].lower()


def test_read_is_never_plan_gated(tmp_path):
    """Reading a file is never blocked, plan or no plan."""
    f = tmp_path / "anything.py"
    f.write_text("line1\nline2\n", encoding="utf-8")
    snippet = (f'<tool_use name="Snippet" id="s1"><param name="file_path">{f}</param>'
               f'<param name="discard">true</param></tool_use>')
    mock = MockLLM([
        f'{METH}\n<tool_use name="Read" id="r1"><param name="file_path">{f}</param></tool_use>',
        f"{METH}\n{snippet}",
        "done.",
    ])
    result = bouzecode(["read it"], mock_llm=mock)
    read_out = _tool_results(result, "Read")[0]
    assert "PLAN REQUIRED" not in read_out
    assert "line1" in read_out
