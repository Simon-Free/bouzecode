# [desc] Tests for ripgrep caching, file-edit safeguards, and external-modification warnings in tools. [/desc]
"""Tests for the 3 mods: ripgrep cache, parallel tool execution, edit safeguards."""
from __future__ import annotations

import os
import time
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

# ── Mod 1: lru_cache on _has_rg ─────────────────────────────────────────────

def test_has_rg_is_cached():
    """_has_rg() should only run the subprocess once (lru_cache)."""
    from tools import _has_rg
    _has_rg.cache_clear()
    result1 = _has_rg()
    result2 = _has_rg()
    assert result1 == result2
    assert _has_rg.cache_info().hits >= 1


# ── Mod 3: File state tracking ──────────────────────────────────────────────

@pytest.fixture()
def tmp_file(tmp_path):
    """Create a temporary file for testing Read/Edit safeguards."""
    f = tmp_path / "test_file.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    return str(f)


@pytest.fixture(autouse=True)
def _reset_file_state():
    """Reset file tracking state before each test."""
    from tools import clear_file_state
    clear_file_state()
    yield
    clear_file_state()


def test_edit_allowed_without_prior_read(tmp_file):
    """Edit should succeed even without a prior Read (trust LLM context)."""
    from tools import _edit
    result = _edit(tmp_file, "line1", "modified1")
    assert "Changes applied" in result
    assert "[Warning]" not in result


def test_edit_allowed_after_read(tmp_file):
    """Edit should succeed after the file has been Read (no warning)."""
    from tools import _read, _edit
    _read(tmp_file)
    result = _edit(tmp_file, "line1", "modified1")
    assert "Changes applied" in result
    assert "[Warning]" not in result


def test_edit_warns_on_external_modification(tmp_file):
    """Edit still applies if file changed on disk, but a warning + diff is included."""
    from tools import _read, _edit
    _read(tmp_file)
    time.sleep(0.05)  # ensure mtime differs
    Path(tmp_file).write_text("externally changed\nline2\nline3\n", encoding="utf-8")
    result = _edit(tmp_file, "line2", "modified2")
    assert "Changes applied" in result
    assert "[Warning]" in result
    assert "modified on disk" in result
    # The warning diff should reflect what changed externally
    assert "externally changed" in result


def test_edit_no_warning_after_re_read(tmp_file):
    """After re-Read, the next Edit on the same file emits no stale warning."""
    from tools import _read, _edit
    _read(tmp_file)
    time.sleep(0.05)
    Path(tmp_file).write_text("new content\nline2\n", encoding="utf-8")
    _read(tmp_file)  # refresh cache
    result = _edit(tmp_file, "new content", "modified")
    assert "Changes applied" in result
    assert "[Warning]" not in result


def test_consecutive_edits_work(tmp_file):
    """Multiple edits on the same file should work (mtime updated after edit)."""
    from tools import _read, _edit
    _read(tmp_file)
    result1 = _edit(tmp_file, "line1", "first_edit")
    assert "Changes applied" in result1
    result2 = _edit(tmp_file, "line2", "second_edit")
    assert "Changes applied" in result2


def test_write_updates_mtime(tmp_file):
    """After Write, the file should be editable without a fresh Read."""
    from tools import _write, _edit
    _write(tmp_file, "written content\n")
    result = _edit(tmp_file, "written content", "edited content")
    assert "Changes applied" in result


def test_clear_file_state_resets_cache(tmp_file):
    """clear_file_state() drops the content cache; edits still apply with no warning."""
    from tools import _read, _edit, clear_file_state, _file_content_cache
    _read(tmp_file)
    assert _file_content_cache  # cache populated
    clear_file_state()
    assert not _file_content_cache  # cache cleared
    # Edit still works (no Read required), and no stale warning since mtime is forgotten too
    result = _edit(tmp_file, "line1", "modified1")
    assert "Changes applied" in result
    assert "[Warning]" not in result


def test_edit_nonexistent_file():
    """Edit on a nonexistent file should return file-not-found error."""
    from tools import _edit
    result = _edit("/nonexistent/path.py", "old", "new")
    assert "not found" in result


# ── Mod 2: DAG-based tool execution levels ─────────────────────────────────

def test_dag_levels_no_deps():
    """Tools with no depends_on should all land in one level (parallel)."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "1", "name": "Read", "input": {"file_path": "a.py"}},
        {"id": "2", "name": "Grep", "input": {"pattern": "foo"}},
        {"id": "3", "name": "Glob", "input": {"pattern": "*.py"}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 1
    assert len(levels[0]) == 3


def test_dag_levels_linear_chain():
    """A→B→C chain should produce 3 levels of 1 tool each."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "1", "name": "Write", "input": {"file_path": "s.py", "content": "x"}},
        {"id": "2", "name": "Bash", "input": {"command": "python s.py", "depends_on": ["1"]}},
        {"id": "3", "name": "Read", "input": {"file_path": "out.txt", "depends_on": ["2"]}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 3
    assert levels[0][0]["id"] == "1"
    assert levels[1][0]["id"] == "2"
    assert levels[2][0]["id"] == "3"


def test_dag_levels_fan_in():
    """Two parallel tasks then one that depends on both (fan-in)."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "1", "name": "Edit", "input": {"file_path": "a.py", "old_string": "x", "new_string": "y"}},
        {"id": "2", "name": "Edit", "input": {"file_path": "b.py", "old_string": "x", "new_string": "y"}},
        {"id": "3", "name": "Bash", "input": {"command": "pytest", "depends_on": ["1", "2"]}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 2
    assert len(levels[0]) == 2  # Both edits in parallel
    assert levels[1][0]["id"] == "3"


def test_dag_levels_implicit_same_file():
    """Edits on the same file should be sequenced implicitly (no depends_on needed)."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "1", "name": "Edit", "input": {"file_path": "a.py", "old_string": "x", "new_string": "y"}},
        {"id": "2", "name": "Edit", "input": {"file_path": "a.py", "old_string": "y", "new_string": "z"}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 2
    assert levels[0][0]["id"] == "1"
    assert levels[1][0]["id"] == "2"


def test_dag_levels_edits_different_files():
    """Edits on different files should be parallelized."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "1", "name": "Edit", "input": {"file_path": "a.py", "old_string": "x", "new_string": "y"}},
        {"id": "2", "name": "Edit", "input": {"file_path": "b.py", "old_string": "x", "new_string": "y"}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 1
    assert len(levels[0]) == 2


def test_dag_levels_empty():
    """Empty list should return empty levels."""
    from agent import _build_dag_levels
    assert _build_dag_levels([]) == ([], {})


def test_dag_levels_ignores_invalid_dep():
    """depends_on referencing non-existent IDs should be ignored."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "1", "name": "Read", "input": {"file_path": "a.py", "depends_on": ["nonexistent"]}},
        {"id": "2", "name": "Read", "input": {"file_path": "b.py"}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 1
    assert len(levels[0]) == 2


def test_dag_levels_depends_on_stripped_from_input():
    """depends_on should be consumed by the DAG builder (popped from input)."""
    from agent import _build_dag_levels

    tc = {"id": "1", "name": "Write", "input": {"file_path": "a.py", "content": "x"}}
    tc2 = {"id": "2", "name": "Bash", "input": {"command": "echo", "depends_on": ["1"]}}
    _build_dag_levels([tc, tc2])
    # depends_on should no longer be in tc2's input
    assert "depends_on" not in tc2["input"]


def test_propagate_denials():
    """Denying a tool should cascade to all its dependents."""
    from agent import _propagate_denials

    all_tcs = [
        {"id": "1", "name": "Write", "input": {"file_path": "a.py", "content": "x"}},
        {"id": "2", "name": "Bash", "input": {"command": "run", "depends_on": ["1"]}},
        {"id": "3", "name": "Read", "input": {"file_path": "out.txt", "depends_on": ["2"]}},
    ]
    permitted_map = {"1": False, "2": True, "3": True}
    denied_results = {"1": "Denied"}

    _propagate_denials(all_tcs, permitted_map, denied_results)

    assert not permitted_map["2"]
    assert not permitted_map["3"]
    assert "dependency was denied" in denied_results["2"]
    assert "dependency was denied" in denied_results["3"]


def test_dag_levels_with_alias():
    """depends_on can reference tool_call_alias instead of real IDs."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "toolu_01", "name": "Write", "input": {"file_path": "a.py", "content": "x", "tool_call_alias": "w1"}},
        {"id": "toolu_02", "name": "Write", "input": {"file_path": "b.py", "content": "y", "tool_call_alias": "w2"}},
        {"id": "toolu_03", "name": "Bash", "input": {"command": "pytest", "depends_on": ["w1", "w2"]}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 2
    assert len(levels[0]) == 2  # Both writes in parallel
    assert levels[1][0]["id"] == "toolu_03"


def test_dag_levels_alias_stripped_from_input():
    """tool_call_alias should be consumed (popped from input)."""
    from agent import _build_dag_levels

    tc = {"id": "1", "name": "Write", "input": {"file_path": "a.py", "content": "x", "tool_call_alias": "w1"}}
    tc2 = {"id": "2", "name": "Bash", "input": {"command": "echo", "depends_on": ["w1"]}}
    _build_dag_levels([tc, tc2])
    assert "tool_call_alias" not in tc["input"]
    assert "depends_on" not in tc2["input"]


def test_dag_levels_alias_mixed_with_ids():
    """depends_on can mix real IDs and aliases."""
    from agent import _build_dag_levels

    tool_calls = [
        {"id": "real_1", "name": "Write", "input": {"file_path": "a.py", "content": "x", "tool_call_alias": "w1"}},
        {"id": "real_2", "name": "Write", "input": {"file_path": "b.py", "content": "y"}},
        {"id": "real_3", "name": "Bash", "input": {"command": "test", "depends_on": ["w1", "real_2"]}},
    ]
    levels, _ = _build_dag_levels(tool_calls)
    assert len(levels) == 2
    assert len(levels[0]) == 2
    assert levels[1][0]["id"] == "real_3"


def test_propagate_denials_with_alias():
    """Denial propagation should work through alias references."""
    from agent import _propagate_denials

    all_tcs = [
        {"id": "1", "name": "Write", "input": {"file_path": "a.py", "content": "x", "tool_call_alias": "w1"}},
        {"id": "2", "name": "Bash", "input": {"command": "run", "depends_on": ["w1"]}},
        {"id": "3", "name": "Read", "input": {"file_path": "out.txt", "depends_on": ["2"]}},
    ]
    permitted_map = {"1": False, "2": True, "3": True}
    denied_results = {"1": "Denied"}

    _propagate_denials(all_tcs, permitted_map, denied_results)

    assert not permitted_map["2"]
    assert not permitted_map["3"]
    assert "dependency was denied" in denied_results["2"]


# ── Orphan tool recovery: _guess_tool_name ────────────────────────────────

def test_guess_tool_name_read():
    from providers import _guess_tool_name
    assert _guess_tool_name({"file_path": "a.py"}) == "Read"


def test_guess_tool_name_read_with_offset():
    from providers import _guess_tool_name
    assert _guess_tool_name({"file_path": "a.py", "offset": 10, "limit": 25}) == "Read"


def test_guess_tool_name_write():
    from providers import _guess_tool_name
    assert _guess_tool_name({"file_path": "a.py", "content": "x"}) == "Write"


def test_guess_tool_name_edit():
    from providers import _guess_tool_name
    assert _guess_tool_name({"file_path": "a.py", "old_string": "x", "new_string": "y"}) == "Edit"


def test_guess_tool_name_bash():
    from providers import _guess_tool_name
    assert _guess_tool_name({"command": "ls"}) == "Bash"


def test_guess_tool_name_grep():
    from providers import _guess_tool_name
    assert _guess_tool_name({"pattern": "foo", "path": "/src"}) == "Grep"


def test_guess_tool_name_glob():
    from providers import _guess_tool_name
    assert _guess_tool_name({"pattern": "*.py"}) == "Glob"


def test_guess_tool_name_unknown():
    from providers import _guess_tool_name
    assert _guess_tool_name({"totally_unknown_key": 1}) == "_UnknownRecoveredTool"


def test_guess_tool_name_ignores_scheduling_keys():
    from providers import _guess_tool_name
    assert _guess_tool_name({"file_path": "a.py", "depends_on": ["w1"], "tool_call_alias": "r1"}) == "Read"


# ── sanitize_messages: orphaned tool_use repair ───────────────────────────

def test_sanitize_messages_adds_missing_tool_results():
    """Orphaned tool_use blocks should get placeholder tool_result messages."""
    from providers import sanitize_messages

    messages = [
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "ok", "tool_calls": [
            {"id": "tc_1", "name": "Read", "input": {"file_path": "a.py"}},
            {"id": "tc_2", "name": "Grep", "input": {"pattern": "foo"}},
            {"id": "tc_3", "name": "Bash", "input": {"command": "ls"}},
        ]},
        # Only 1 tool result out of 3
        {"role": "tool", "tool_call_id": "tc_1", "name": "Read", "content": "file contents"},
        {"role": "user", "content": "Continue."},
    ]
    fixed = sanitize_messages(messages)
    tool_msgs = [m for m in fixed if m["role"] == "tool"]
    assert len(tool_msgs) == 3
    placeholder_ids = {m["tool_call_id"] for m in tool_msgs if "interrupted" in m["content"]}
    assert placeholder_ids == {"tc_2", "tc_3"}


def test_sanitize_messages_no_change_when_complete():
    """Messages with all tool_results present should pass through unchanged."""
    from providers import sanitize_messages

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "I'll read", "tool_calls": [
            {"id": "tc_1", "name": "Read", "input": {"file_path": "a.py"}},
        ]},
        {"role": "tool", "tool_call_id": "tc_1", "name": "Read", "content": "ok"},
        {"role": "assistant", "content": "done", "tool_calls": []},
    ]
    fixed = sanitize_messages(messages)
    assert fixed == messages


def test_sanitize_messages_all_missing():
    """All tool_results missing — all should be filled with placeholders."""
    from providers import sanitize_messages

    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc_a", "name": "Bash", "input": {"command": "echo hi"}},
            {"id": "tc_b", "name": "Read", "input": {"file_path": "x.py"}},
        ]},
        # No tool results at all — next message is user
        {"role": "user", "content": "Continue."},
    ]
    fixed = sanitize_messages(messages)
    tool_msgs = [m for m in fixed if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert all("interrupted" in m["content"] for m in tool_msgs)


def test_messages_to_anthropic_with_orphans():
    """messages_to_anthropic produces valid XML output even with orphaned tool_use.

    With the XML protocol, tool_use and tool_result are XML text. Sanitization
    injects placeholder tool_results for any tool_call that lacks a real result
    (so the model never sees an unmatched tool_use)."""
    from providers import messages_to_anthropic

    messages = [
        {"role": "user", "content": "test"},
        {"role": "assistant", "content": "calling tools", "tool_calls": [
            {"id": "tc_1", "name": "Read", "input": {"file_path": "a.py"}},
            {"id": "tc_2", "name": "Grep", "input": {"pattern": "x"}},
        ]},
        # Zero tool results
        {"role": "user", "content": "what happened?"},
    ]
    result = messages_to_anthropic(messages)
    all_text = " ".join(
        m["content"] for m in result if isinstance(m["content"], str)
    )
    assert all_text.count("<tool_result") == 2
    assert 'id="tc_1"' in all_text
    assert 'id="tc_2"' in all_text
