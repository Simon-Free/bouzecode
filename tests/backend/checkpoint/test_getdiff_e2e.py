# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">Conversation-level e2e tests verifying GetDiff tool output after Write/Edit operations via MockLLM harness.</param></tool_use> [/desc]
"""GetDiff observed through real bouzecode() conversations.

Replaces the direct _get_diff(...) unit tests in test_getdiff_revert.py
(TestGetDiff): the (mocked) model Writes/Edits a temp_ file (exempt from plan
mode), then calls GetDiff, and we assert on the diff tool_result the loop
produced. The Write/Edit really runs, so record_file_snapshot populates the
turn's snapshots — exactly what a user sees when reviewing changes before a
revert. GetDiff is a non-meta tool, so a Methodology+Write+GetDiff batch
continues and needs a follow-up turn to close.

The /revert command (cmd_revert) is NOT covered here: it is a slash command
dispatched by the REPL, not a tool reachable from the agent loop, so a MockLLM
conversation cannot drive it. Those tests stay as units in test_getdiff_revert.py.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.tools.state import clear_file_state

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


@pytest.fixture(autouse=True)
def _clean_snapshots():
    clear_file_state()
    yield
    clear_file_state()


def _write(path, content, tid="w1"):
    return (f'<tool_use name="Write" id="{tid}"><param name="file_path">{path}</param>'
            f'<param name="content">{content}</param></tool_use>')


def _edit(path, old, new, tid="e1"):
    return (f'<tool_use name="Edit" id="{tid}"><param name="file_path">{path}</param>'
            f'<param name="old_string">{old}</param><param name="new_string">{new}</param></tool_use>')


def _getdiff(file_path=None, tid="g1"):
    fp = f'<param name="file_path">{file_path}</param>' if file_path else ""
    return f'<tool_use name="GetDiff" id="{tid}">{fp}</tool_use>'


def _tool_results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


# ── new file: GetDiff shows the addition ─────────────────────────────────────

def test_write_then_getdiff_shows_new_file(tmp_path):
    f = tmp_path / "temp_app.py"
    mock = MockLLM([
        f"{METH}\n{_write(f, 'def main(): pass\n')}",
        f"{METH}\n{_getdiff()}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["build it"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "temp_app.py" in diff
    assert "def main()" in diff
    assert "No changes recorded." not in diff


# ── edit: GetDiff shows before/after of a real modification ───────────────────

def test_edit_then_getdiff_shows_before_and_after(tmp_path):
    f = tmp_path / "temp_mod.py"
    f.write_text("def hello():\n    pass\n", encoding="utf-8")
    edit = _edit(f, "pass", "print('hi')")
    read = f'<tool_use name="Read" id="r1"><param name="file_path">{f}</param></tool_use>'
    discard = (f'<tool_use name="Snippet" id="s1"><param name="file_path">{f}</param>'
               f'<param name="discard">true</param></tool_use>')
    mock = MockLLM([
        # Read first so Edit isn't blocked by the read-before-edit safeguard.
        f"{METH}\n{read}",
        # Cover the Read (Snippet discard) and apply the edit in the same batch.
        f"{METH}\n{discard}\n{edit}",
        f"{METH}\n{_getdiff()}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["change it"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "-    pass" in diff
    assert "+    print('hi')" in diff


# ── path filter: only the requested file appears ─────────────────────────────

def test_getdiff_filter_by_path_excludes_other_files(tmp_path):
    fa = tmp_path / "temp_a.py"
    fb = tmp_path / "temp_b.py"
    mock = MockLLM([
        f"{METH}\n{_write(fa, 'aaa\n', 'w1')}\n{_write(fb, 'bbb\n', 'w2')}",
        f"{METH}\n{_getdiff(file_path=fa)}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["write two files"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "temp_a.py" in diff
    assert "temp_b.py" not in diff
    assert "aaa" in diff and "bbb" not in diff


def test_getdiff_filter_nonexistent_path_reports_no_changes(tmp_path):
    fa = tmp_path / "temp_a.py"
    missing = tmp_path / "temp_nope.py"
    mock = MockLLM([
        f"{METH}\n{_write(fa, 'aaa\n')}",
        f"{METH}\n{_getdiff(file_path=missing)}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["write a file"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "No changes for" in diff
    assert "temp_nope.py" in diff


# ── no edits yet: GetDiff reports nothing recorded ───────────────────────────

def test_getdiff_with_no_edits_reports_no_changes(tmp_path):
    mock = MockLLM([
        f"{METH}\n{_getdiff()}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["show me the diff"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert diff == "No changes recorded."
