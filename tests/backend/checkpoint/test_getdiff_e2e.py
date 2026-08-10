# [desc] Conversation feature tests for reviewing and undoing changes: the agent Writes/Edits files, GetDiff shows what changed, and /revert puts the files back. [/desc]
"""Reviewing and undoing an agent's changes, from real bouzecode() conversations.

Replaces the direct _get_diff(...) unit tests in test_getdiff_revert.py
(TestGetDiff): the (mocked) model Writes/Edits a file, then calls GetDiff, and we
assert on the diff tool_result the loop produced. The Write/Edit really runs, so
the turn's snapshots are populated — exactly what a user sees when reviewing
changes before undoing them. GetDiff is a non-meta tool, so a
Methodology+Write+GetDiff batch continues and needs a follow-up turn to close.

/revert is a slash command the REPL dispatches, not a tool the model can emit, so
the last test drives it the way the REPL does: it checkpoints after each user
turn (ckpt.make_snapshot), then runs the REAL cmd_revert on the state the
conversation produced. Its bookkeeping side (message/token rewind, missing
session, no checkpoints) stays a unit in test_getdiff_revert.py.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend import checkpoint as ckpt
from bouzecode.backend.commands.session.revert_cmd import cmd_revert
from bouzecode.backend.tools.state import clear_file_state

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


@pytest.fixture(autouse=True)
def _clean_snapshots():
    clear_file_state()
    yield
    clear_file_state()


@pytest.fixture
def checkpointed_session(tmp_path, monkeypatch):
    """Set up what the REPL sets up around a conversation: an isolated checkpoint
    store and an active session, so Write/Edit are backed up for real.

    The session id is set through monkeypatch rather than ckpt.set_session
    because set_session has no counterpart to unset it — monkeypatch restores it,
    so a later test's Write is not silently backed up under this session.
    """
    import bouzecode.backend.checkpoint.store as store
    monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")
    monkeypatch.setattr(
        "bouzecode.backend.checkpoint.hooks._current_session_id", "revert_story"
    )
    ckpt.reset_tracked()
    yield "revert_story"
    ckpt.reset_tracked()


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
    write_call = _write(f, "def main(): pass\n")
    mock = MockLLM([
        f"{METH}\n{write_call}",
        f"{METH}\n{_getdiff()}",
        "done.",
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
        "done.",
    ])
    result = bouzecode(["change it"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "-    pass" in diff
    assert "+    print('hi')" in diff


# ── path filter: only the requested file appears ─────────────────────────────

def test_getdiff_filter_by_path_excludes_other_files(tmp_path):
    fa = tmp_path / "temp_a.py"
    fb = tmp_path / "temp_b.py"
    write_a, write_b = _write(fa, "aaa\n", "w1"), _write(fb, "bbb\n", "w2")
    mock = MockLLM([
        f"{METH}\n{write_a}\n{write_b}",
        f"{METH}\n{_getdiff(file_path=fa)}",
        "done.",
    ])
    result = bouzecode(["write two files"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "temp_a.py" in diff
    assert "temp_b.py" not in diff
    assert "aaa" in diff and "bbb" not in diff


def test_getdiff_filter_nonexistent_path_reports_no_changes(tmp_path):
    fa = tmp_path / "temp_a.py"
    missing = tmp_path / "temp_nope.py"
    write_a = _write(fa, "aaa\n")
    mock = MockLLM([
        f"{METH}\n{write_a}",
        f"{METH}\n{_getdiff(file_path=missing)}",
        "done.",
    ])
    result = bouzecode(["write a file"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert "No changes for" in diff
    assert "temp_nope.py" in diff


# ── no edits yet: GetDiff reports nothing recorded ───────────────────────────

def test_getdiff_with_no_edits_reports_no_changes(tmp_path):
    mock = MockLLM([
        f"{METH}\n{_getdiff()}",
        "done.",
    ])
    result = bouzecode(["show me the diff"], mock_llm=mock)
    diff = _tool_results(result, "GetDiff")[0]
    assert diff == "No changes recorded."


# ── /revert: the user changes their mind about the last request ──────────────

def test_revert_restores_the_file_as_it_was_before_the_last_request(
    tmp_path, checkpointed_session
):
    """The user asks for a change, doesn't like it, and types /revert: the file
    goes back to the version checkpointed at the end of the previous request."""
    session_id = checkpointed_session
    config = {"_session_id": session_id}
    target = tmp_path / "temp_config.py"

    def checkpoint_after_turn(state, user_message):
        """What the REPL does at the end of every user turn."""
        ckpt.make_snapshot(session_id, state, config, user_message,
                           tracked_edits=ckpt.get_tracked_edits())
        ckpt.reset_tracked()

    first = bouzecode(
        ["create the config with port 8080"],
        mock_llm=MockLLM([f"{METH}\n{_write(target, 'PORT = 8080')}", "done."]),
    )
    checkpoint_after_turn(first.state, "create the config with port 8080")
    assert "PORT = 8080" in target.read_text(encoding="utf-8")

    second = bouzecode(
        ["actually use port 9090"],
        mock_llm=MockLLM([f"{METH}\n{_write(target, 'PORT = 9090')}", "done."]),
    )
    checkpoint_after_turn(second.state, "actually use port 9090")
    assert "PORT = 9090" in target.read_text(encoding="utf-8")

    cmd_revert("", second.state, config)

    assert "PORT = 8080" in target.read_text(encoding="utf-8")
    assert "9090" not in target.read_text(encoding="utf-8")
