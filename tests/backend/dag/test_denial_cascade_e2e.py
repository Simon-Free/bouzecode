# [desc] Conversation tests: a denied tool call cancels every call that declared depends_on on it, in each accepted depends_on syntax. [/desc]
"""Denying one call must cancel the calls that wait for it — whatever syntax they used.

The XML parser hands `depends_on` over as raw text: `depends_on=["w1"]` and
`depends_on="["w1"]"` both arrive as the literal string `["w1"]`. Read as ONE alias
named `["w1"]` it matched nothing, so a dependent of a denied call ran anyway — on a
half-built state it was explicitly told to wait for.

These are conversations, not unit tests, but they cannot use `tests.e2e_harness`:
that harness force-permits every call (`_check_permission = lambda tc, c: True`), which
is precisely the code under test. So the loop is driven here with the SAME patches minus
that one, and denial is produced the only deterministic way a real session can produce it
without a human: plan mode, where a Write outside the plan file is refused.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState, ToolEnd
from bouzecode.backend.core.config import load_config
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."
SKIPPED = "Skipped: a dependency was denied"


def _write(path, tc_id, alias):
    return (f'<tool_use name="Write" id="{tc_id}" tool_call_alias="{alias}">'
            f'<param name="file_path">{path}</param>'
            f'<param name="content">x = 1</param></tool_use>')


def _glob(pattern, depends_on=None):
    """Glob is read-only, so plan mode permits it: if it ends up cancelled, the
    cascade is the only possible cause."""
    dep = f'<param name="depends_on">{depends_on}</param>' if depends_on else ""
    return (f'<tool_use name="Glob" id="g1">'
            f'<param name="pattern">{pattern}</param>{dep}</tool_use>')


def _run_in_plan_mode(monkeypatch, responses):
    """Drive a real conversation with real permission checks, in plan mode."""
    import bouzecode.backend.agent.loop_turn as lt

    mock = MockLLM(responses)
    monkeypatch.setattr(lt, "stream", mock.stream)
    monkeypatch.setattr(lt, "get_tool_schemas", lambda *a, **k: [])
    monkeypatch.setattr(lt, "is_web_ipc_active", lambda: False)

    config = load_config()
    config.update({
        "permission_mode": "plan",     # Write refused, read-only tools allowed
        "verbose": False,
        "task_classification": False,
        "close_validation": False,
        "_cwd": tempfile.mkdtemp(prefix="bouzecode_denial_"),
    })
    state = AgentState()
    events = list(run("go", state, config, "You are a helpful assistant."))
    return [e for e in events if isinstance(e, ToolEnd)]


def _tool_end(tool_ends, name):
    matches = [e for e in tool_ends if e.name == name]
    assert matches, f"no {name} result in {[e.name for e in tool_ends]}"
    return matches[0]


@pytest.mark.parametrize("syntax,depends_on", [
    ("json array (what the XML parser delivers)", '["w1"]'),
    ("python repr", "['w1']"),
    ("plain alias", "w1"),
])
def test_dependent_of_a_denied_call_is_cancelled(monkeypatch, tmp_path, syntax, depends_on):
    """A Glob that declared depends_on on a REFUSED Write never runs, whatever
    syntax the model used to declare the dependency."""
    tool_ends = _run_in_plan_mode(monkeypatch, [
        f"{METH}\n{_write(tmp_path / 'temp_a.py', 'w_1', 'w1')}\n"
        f"{_glob('*.py', depends_on=depends_on)}",
        CLOSE,
    ])

    glob_end = _tool_end(tool_ends, "Glob")
    assert not glob_end.permitted, f"{syntax}: the dependent was allowed to run"
    assert SKIPPED in glob_end.result, f"{syntax}: got {glob_end.result!r}"


def test_comma_separated_dependencies_are_all_honoured(monkeypatch, tmp_path):
    """`depends_on` listing two aliases comma-separated: refusing either one cancels
    the dependent."""
    tool_ends = _run_in_plan_mode(monkeypatch, [
        f"{METH}\n{_write(tmp_path / 'temp_a.py', 'w_1', 'w1')}\n"
        f"{_write(tmp_path / 'temp_b.py', 'w_2', 'w2')}\n"
        f"{_glob('*.py', depends_on='w1,w2')}",
        CLOSE,
    ])

    glob_end = _tool_end(tool_ends, "Glob")
    assert not glob_end.permitted
    assert SKIPPED in glob_end.result


def test_glob_without_depends_on_still_runs_while_the_write_is_refused(monkeypatch, tmp_path):
    """Control: the same batch WITHOUT depends_on. The Write is still refused, but the
    Glob is independent and runs for real — so the cancellation above really comes from
    the declared dependency, not from plan mode refusing read-only tools."""
    (tmp_path / "already_here.py").write_text("y = 2\n", encoding="utf-8")
    tool_ends = _run_in_plan_mode(monkeypatch, [
        f"{METH}\n{_write(tmp_path / 'temp_a.py', 'w_1', 'w1')}\n"
        f'<tool_use name="Glob" id="g1"><param name="pattern">*.py</param>'
        f'<param name="path">{tmp_path.as_posix()}</param></tool_use>',
        CLOSE,
    ])

    write_end = _tool_end(tool_ends, "Write")
    assert not write_end.permitted            # plan mode still refuses the write
    glob_end = _tool_end(tool_ends, "Glob")
    assert glob_end.permitted
    assert SKIPPED not in glob_end.result
    assert "already_here.py" in glob_end.result
