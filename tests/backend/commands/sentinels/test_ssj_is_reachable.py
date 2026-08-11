# [desc] Verrou : /ssj est atteignable, reçoit la config vivante et rend une sentinelle __ssj_*. [/desc]
"""`/ssj` must be reachable, not merely implemented.

`cmd_ssj` was imported by `dispatcher.py` and left out of `COMMANDS`, so typing `/ssj`
printed "Unknown command". The tests go through `handle_slash`, the REPL's own entry
point, and check the tuple it hands back — that tuple *is* the contract of a sentinel
command (`ui/repl_sentinels.py` acts on it).

The command is an interactive menu that loops on `ask_input_interactive` until a choice
produces a sentinel. A test cannot type at a terminal, so that single input function is
replaced by a scripted reader: an ordinary function, no `unittest.mock`. It also records
the config object it is handed, which is how the "the live config reaches the command"
half of the contract is checked — the dispatcher must pass the caller's dict, not a copy.

Nothing here touches the network, a process or a window: the menu only reads a todo file
under `tmp_path`.
"""
from __future__ import annotations

import inspect

import pytest

from bouzecode.backend.commands import ssj
from bouzecode.backend.commands.dispatcher import COMMANDS, handle_slash


@pytest.fixture
def scripted_menu(monkeypatch):
    """Answer the menu's questions in order; return the configs it was handed."""
    def _answering(*answers: str) -> list[dict]:
        remaining = list(answers)
        seen_configs: list[dict] = []

        def _read(_prompt, config, _menu_text=None):
            seen_configs.append(config)
            return remaining.pop(0)

        monkeypatch.setattr(ssj, "ask_input_interactive", _read)
        return seen_configs

    return _answering


def test_slash_ssj_hands_a_typed_command_back_to_the_repl(scripted_menu):
    """A slash typed at the menu comes back as a passthrough for the loop to dispatch."""
    scripted_menu("/context")

    assert handle_slash("/ssj", None, {}) == ("__ssj_passthrough__", "/context")


def test_slash_ssj_builds_a_worker_command_from_the_answers(scripted_menu, tmp_path,
                                                            monkeypatch):
    """Menu entry 3 collects three answers and forwards them as `/worker` arguments."""
    monkeypatch.chdir(tmp_path)
    todo = tmp_path / "todo_list.txt"
    todo.write_text("- [ ] a task\n", encoding="utf-8")
    scripted_menu("3", str(todo), "1", "2")

    assert handle_slash("/ssj", None, {}) == (
        "__ssj_cmd__", "worker", f"--path {todo} --tasks 1 --workers 2",
    )


def test_slash_ssj_turns_a_review_choice_into_a_query(scripted_menu, tmp_path,
                                                      monkeypatch):
    """Menu entry 6 picks a file from the working directory and returns a prompt."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "subject.py").write_text("x = 1\n", encoding="utf-8")
    scripted_menu("6", "1")

    sentinel, prompt = handle_slash("/ssj", None, {})

    assert sentinel == "__ssj_query__"
    assert "subject.py" in prompt


def test_slash_ssj_receives_the_live_config(scripted_menu):
    """Every question is asked with the caller's own config dict, not a copy."""
    config = {"model": "a-model"}
    seen_configs = scripted_menu("/context")

    handle_slash("/ssj", None, config)

    assert seen_configs and all(seen is config for seen in seen_configs)


def test_slash_ssj_leaves_the_menu_without_a_sentinel(scripted_menu, capsys):
    """Choosing 0 ends the menu: handled, nothing handed back to the loop."""
    scripted_menu("0")

    assert handle_slash("/ssj", None, {}) is True
    assert "Exiting SSJ Mode" in capsys.readouterr().out


def test_help_lists_ssj(capsys):
    """`/help` prints `_CMD_META`, so a wired command must appear there."""
    handle_slash("/help", None, {})

    assert "/ssj" in capsys.readouterr().out


def test_ssj_handler_matches_the_dispatcher_calling_convention():
    """`handle_slash` calls `handler(args, state, config)` positionally."""
    parameters = list(inspect.signature(COMMANDS["ssj"]).parameters.values())

    assert len(parameters) == 3
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters)
