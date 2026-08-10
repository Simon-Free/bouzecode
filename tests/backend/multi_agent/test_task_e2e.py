# [desc] Conversation feature tests for the Task tools: the model creates/updates/gets/lists/deletes tasks and the store reflects it, observed through real bouzecode() turns. [/desc]
"""Task tool behaviour through real bouzecode() conversations.

Replaces the direct-call unit tests in test_task.py (TestTaskStore and
TestTaskToolFunctions): the (mocked) model emits TaskCreate / TaskUpdate /
TaskGet / TaskList tool calls and we assert on the tool_result the loop produced
plus the resulting store state — exactly what a user observes when the agent
manages its task list. The task tools really execute (no mock_tools), against an
isolated store.

KEPT AS UNIT in test_task.py (not conversation-observable):
- TestTaskTypes: Task dataclass serialization (to_dict/from_dict roundtrip),
  status_icon glyphs, one_line() formatting, unknown-status defaulting. Pure
  data-structure invariants — the conversation only sees the rendered tool
  strings, never the Task object internals.
- TestTaskStore reverse-edge bookkeeping (add_blocks registers the reverse
  blocked_by edge on the target, and vice-versa): the *observable* blocker
  display is covered here (test_list_hides_blocker_once_resolved), but the
  internal symmetric-edge invariant on the Task objects is not visible from a
  conversation.
- test_ids_are_sequential / test_next_id: ID-sequence algorithm internal.
- test_persistence_round_trip: disk reload of the global store.
- test_thread_safety: concurrent-create ID uniqueness (concurrency).
- test_tool_schemas_registered / _in_tool_schemas_list: static config
  invariants (discoverability of the tool by the model) — the harness stubs
  get_tool_schemas, so a conversation cannot assert the schema is present.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
import bouzecode.backend.tools.task.store as _store

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# Closing reply: PLAIN TEXT, no tool call. A Methodology/Snippet-only batch is
# bookkeeping — since b83ade94 it never closes the session, it earns a
# continue-nudge. Only FinalAnswer or a tool-call-free reply closes.
CLOSE = "C'est fait."


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Each test gets a fresh in-memory + on-disk task store, with the Task
    tools enabled (TaskCreate/Update/Get are disabled by default in the
    whitelist — the conversation here exercises them directly)."""
    from bouzecode.backend.core.tool_registry import enable_tool, disable_tool, _disabled
    monkeypatch.setattr(_store, "_tasks", {})
    monkeypatch.setattr(_store, "_loaded", False)
    monkeypatch.setattr(_store, "_tasks_file", lambda: tmp_path / ".bouzecode" / "tasks.json")
    _task_tools = ("TaskCreate", "TaskUpdate", "TaskGet", "TaskList")
    _was_disabled = [t for t in _task_tools if t in _disabled]
    for t in _task_tools:
        enable_tool(t)
    yield
    for t in _was_disabled:
        disable_tool(t)
    _store._tasks.clear()
    _store._loaded = False


def _create(subject, description, tid="c1"):
    return (f'<tool_use name="TaskCreate" id="{tid}">'
            f'<param name="subject">{subject}</param>'
            f'<param name="description">{description}</param></tool_use>')


def _update(task_id, tid="u1", **params):
    body = f'<param name="task_id">{task_id}</param>'
    for k, v in params.items():
        body += f'<param name="{k}">{v}</param>'
    return f'<tool_use name="TaskUpdate" id="{tid}">{body}</tool_use>'


def _get(task_id, tid="g1"):
    return f'<tool_use name="TaskGet" id="{tid}"><param name="task_id">{task_id}</param></tool_use>'


def _list(tid="l1"):
    return f'<tool_use name="TaskList" id="{tid}"></tool_use>'


def _tool_results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


# ── create → list ────────────────────────────────────────────────────────────

def test_create_then_appears_in_list():
    mock = MockLLM([
        f"{METH}\n{_create('Write docs', 'Document everything')}",
        f"{METH}\n{_list()}",
        CLOSE,
    ])
    result = bouzecode(["track work"], mock_llm=mock)
    assert _tool_results(result, "TaskCreate")[0] == "Task #1 created: Write docs"
    listed = _tool_results(result, "TaskList")[0]
    assert "#1" in listed
    assert "Write docs" in listed
    assert "pending" in listed


def test_list_empty_when_no_tasks():
    mock = MockLLM([f"{METH}\n{_list()}", CLOSE])
    result = bouzecode(["what's on the list"], mock_llm=mock)
    assert _tool_results(result, "TaskList")[0] == "No tasks."


def test_multiple_creates_get_sequential_ids_in_list():
    mock = MockLLM([
        f"{METH}\n{_create('Step 1', 'first', 'c1')}\n{_create('Step 2', 'second', 'c2')}",
        f"{METH}\n{_list()}",
        CLOSE,
    ])
    result = bouzecode(["plan it"], mock_llm=mock)
    creates = _tool_results(result, "TaskCreate")
    assert creates[0] == "Task #1 created: Step 1"
    assert creates[1] == "Task #2 created: Step 2"
    listed = _tool_results(result, "TaskList")[0]
    assert "#1" in listed and "#2" in listed


# ── update status ────────────────────────────────────────────────────────────

def test_update_status_reflected_in_get():
    mock = MockLLM([
        f"{METH}\n{_create('Fix lint', 'run ruff')}",
        f"{METH}\n{_update('1', status='in_progress')}",
        f"{METH}\n{_get('1')}",
        CLOSE,
    ])
    result = bouzecode(["start work"], mock_llm=mock)
    upd = _tool_results(result, "TaskUpdate")[0]
    assert "updated" in upd.lower()
    assert "status" in upd
    got = _tool_results(result, "TaskGet")[0]
    assert "in_progress" in got


def test_update_subject_and_owner():
    mock = MockLLM([
        f"{METH}\n{_create('Old title', 'old desc')}",
        f"{METH}\n{_update('1', subject='New title', owner='alice')}",
        f"{METH}\n{_get('1')}",
        CLOSE,
    ])
    result = bouzecode(["rename"], mock_llm=mock)
    got = _tool_results(result, "TaskGet")[0]
    assert "New title" in got
    assert "alice" in got


def test_update_no_changes_reports_no_op():
    mock = MockLLM([
        f"{METH}\n{_create('Same', 'desc')}",
        f"{METH}\n{_update('1', subject='Same')}",
        CLOSE,
    ])
    result = bouzecode(["touch it"], mock_llm=mock)
    upd = _tool_results(result, "TaskUpdate")[0]
    assert "no changes" in upd.lower()


def test_update_unknown_task_reports_not_found():
    mock = MockLLM([
        f"{METH}\n{_update('999', status='completed')}",
        CLOSE,
    ])
    result = bouzecode(["update ghost"], mock_llm=mock)
    assert "not found" in _tool_results(result, "TaskUpdate")[0].lower()


# ── delete via status=deleted ────────────────────────────────────────────────

def test_delete_removes_from_list():
    mock = MockLLM([
        f"{METH}\n{_create('Temp task', 'will go')}",
        f"{METH}\n{_update('1', status='deleted')}",
        f"{METH}\n{_list()}",
        CLOSE,
    ])
    result = bouzecode(["delete it"], mock_llm=mock)
    upd = _tool_results(result, "TaskUpdate")[0]
    assert "deleted" in upd.lower()
    assert _tool_results(result, "TaskList")[0] == "No tasks."


# ── get ──────────────────────────────────────────────────────────────────────

def test_get_returns_details():
    mock = MockLLM([
        f"{METH}\n{_create('Review PR', 'check the diff')}",
        f"{METH}\n{_get('1')}",
        CLOSE,
    ])
    result = bouzecode(["show task"], mock_llm=mock)
    got = _tool_results(result, "TaskGet")[0]
    assert "Review PR" in got
    assert "pending" in got
    assert "check the diff" in got


def test_get_unknown_reports_not_found():
    mock = MockLLM([f"{METH}\n{_get('999')}", CLOSE])
    result = bouzecode(["show ghost"], mock_llm=mock)
    assert "not found" in _tool_results(result, "TaskGet")[0].lower()


# ── blockers: resolved blocker hidden in list ────────────────────────────────

def test_list_hides_blocker_once_resolved():
    block_b_on_a = _update("2", tid="u1", add_blocked_by='["1"]')
    mock = MockLLM([
        f"{METH}\n{_create('Step A', 'first step', 'c1')}\n{_create('Step B', 'second step', 'c2')}",
        f"{METH}\n{block_b_on_a}",
        f"{METH}\n{_list('l1')}",                                # B shows [blocked by #1]
        f"{METH}\n{_update('1', tid='u2', status='completed')}",
        f"{METH}\n{_list('l2')}",                                # blocker resolved → hidden
        CLOSE,
    ])
    result = bouzecode(["set up deps"], mock_llm=mock)
    lists = _tool_results(result, "TaskList")
    before, after = lists[0], lists[1]
    b_before = [ln for ln in before.splitlines() if "#2" in ln][0]
    assert "blocked by" in b_before.lower()
    b_after = [ln for ln in after.splitlines() if "#2" in ln][0]
    assert "blocked by" not in b_after.lower()
