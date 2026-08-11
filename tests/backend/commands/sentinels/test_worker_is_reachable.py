# [desc] Verrou : /worker est atteignable via handle_slash et rend la sentinelle __worker__. [/desc]
"""`/worker` must be reachable, not merely implemented.

`cmd_worker` was imported by `dispatcher.py` and left out of `COMMANDS`, so typing
`/worker` printed "Unknown command" — the defect `/telegram` had. These tests therefore
go through `handle_slash`, the entry point the REPL itself uses, rather than reading the
table, which would prove nothing.

A sentinel command does no work of its own: it hands a tuple back to the loop, which then
runs the tasks (`ui/repl_sentinels.py`). The contract to check is therefore the tuple.
`--path` points at a temporary todo file, so nothing in the checkout is read and no task
is ever executed.

`state` is unused by this command, hence the `None` below: the dispatcher passes it
positionally and `cmd_worker` never touches it.
"""
from __future__ import annotations

import inspect

import pytest

from bouzecode.backend.commands.dispatcher import COMMANDS, handle_slash


@pytest.fixture
def todo_file(tmp_path):
    path = tmp_path / "todo_list.txt"
    path.write_text(
        "- [x] already done\n"
        "- [ ] first pending task\n"
        "- [ ] second pending task\n",
        encoding="utf-8",
    )
    return path


def _task_texts(tasks) -> list[str]:
    return [text for _line_index, text, _prompt in tasks]


def test_slash_worker_returns_one_prompt_per_pending_task(todo_file):
    """The sentinel carries the pending tasks, and only those — `- [x]` is skipped."""
    sentinel, tasks = handle_slash(f"/worker --path {todo_file}", None, {})

    assert sentinel == "__worker__"
    assert _task_texts(tasks) == ["first pending task", "second pending task"]
    assert "first pending task" in tasks[0][2], "the prompt must quote the task"


def test_slash_worker_forwards_its_arguments(todo_file):
    """The text after the command name reaches the handler and is parsed there."""
    _sentinel, tasks = handle_slash(f"/worker --path {todo_file} --tasks 2", None, {})

    assert _task_texts(tasks) == ["second pending task"]


def test_slash_worker_caps_the_batch_at_the_requested_worker_count(todo_file):
    _sentinel, tasks = handle_slash(f"/worker --path {todo_file} --workers 1", None, {})

    assert _task_texts(tasks) == ["first pending task"]


def test_slash_worker_refuses_a_task_number_out_of_range(todo_file, capsys):
    """A rejected selection is handled without a sentinel: the REPL has nothing to run."""
    assert handle_slash(f"/worker --path {todo_file} --tasks 9", None, {}) is True
    assert "out of range" in capsys.readouterr().err


def test_slash_worker_reports_a_missing_todo_file(tmp_path, capsys):
    assert handle_slash(f"/worker --path {tmp_path / 'absent.txt'}", None, {}) is True
    assert "No todo file found" in capsys.readouterr().err


def test_help_lists_worker(capsys):
    """`/help` prints `_CMD_META`, so a wired command must appear there."""
    handle_slash("/help", None, {})

    assert "/worker" in capsys.readouterr().out


def test_worker_handler_matches_the_dispatcher_calling_convention():
    """`handle_slash` calls `handler(args, state, config)` positionally."""
    parameters = list(inspect.signature(COMMANDS["worker"]).parameters.values())

    assert len(parameters) == 3
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters)
