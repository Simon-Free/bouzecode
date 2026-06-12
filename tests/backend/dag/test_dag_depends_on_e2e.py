# [desc] E2e tests verifying DAG depends_on ordering ensures Write executes before Bash in bouzecode conversations
# <tool_use name="FinalAnswer" id="f1"><param name="answer">E2e tests verifying DAG depends_on ordering ensures Write executes before Bash in bouzecode conversations</param></tool_use> [/desc]
"""DAG dependency ordering observed through real bouzecode() conversations.

Replaces the OBSERVABLE part of the _build_dag_levels unit tests in
test_dag_depends_on.py: when the model emits a parallel batch where a Bash
depends on a Write (explicitly via depends_on, or implicitly because the Bash
command references the written file's basename), the loop must run the Write
first so the Bash sees the file. We prove this end to end by writing a tiny
Python script and running it: if the dependency is honoured the Bash output
contains the script's marker; if the DAG raced or ordered wrong the file would
not exist yet.

This exercises the full real path: XML parse of depends_on -> _coerce_list ->
_build_alias_map -> _build_dag_levels -> _inject_write_bash_deps -> level-by-level
execution with real Write and Bash tools.

KEPT AS UNITS in test_dag_depends_on.py (justified there):
- TestCoerceList: pure string/JSON/None parsing permutations — a helper, not a
  conversation behaviour.
- The _build_dag_levels assertions on `levels`/`deps` shapes that no real tool
  output reflects (e.g. exact level counts, delete-chain dep absence) — internal
  data-structure invariants. Tool-result *position* in result.messages follows
  the original batch order, not execution order (see loop_turn append loop), so
  ordering is only observable via tool-result *content*, which is what we assert.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
MARKER = "DAG_ORDER_OK"


def _write(path, tid="w1"):
    return (f'<tool_use name="Write" id="{tid}"><param name="file_path">{path}</param>'
            f'<param name="content">print("{MARKER}")</param></tool_use>')


def _bash(path, tid="b1", depends_on=None):
    dep = (f'<param name="depends_on">{depends_on}</param>') if depends_on else ""
    return (f'<tool_use name="Bash" id="{tid}"><param name="command">python {path}</param>'
            f'{dep}</tool_use>')


def _tool_results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


def _bash_saw_marker(result):
    return any(MARKER in r for r in _tool_results(result, "Bash"))


# ── explicit depends_on (JSON-string param, as the XML parser delivers it) ────

def test_explicit_depends_on_runs_write_before_bash(tmp_path):
    """Bash depends_on ["w1"] (a JSON string after XML parse) -> Write runs first."""
    f = tmp_path / "temp_script.py"
    mock = MockLLM([
        f'{METH}\n{_write(f)}\n{_bash(f, depends_on="[\"w1\"]")}',
        f"done.\n{METH}",
    ])
    result = bouzecode(["go"], mock_llm=mock)
    assert _bash_saw_marker(result)


def test_explicit_depends_on_plain_string_alias(tmp_path):
    """depends_on as a plain alias string 'w1' also orders Write before Bash."""
    f = tmp_path / "temp_script.py"
    mock = MockLLM([
        f'{METH}\n{_write(f)}\n{_bash(f, depends_on="w1")}',
        f"done.\n{METH}",
    ])
    result = bouzecode(["go"], mock_llm=mock)
    assert _bash_saw_marker(result)


# ── auto-injection by basename (model forgot depends_on) ─────────────────────

def test_auto_injects_dep_when_bash_listed_before_write(tmp_path):
    """No depends_on; Bash is emitted BEFORE the Write in the batch. Auto-injection
    by basename must still order the Write first so the Bash sees the file."""
    f = tmp_path / "temp_script.py"
    # Bash first, then Write — only the basename match can save the ordering.
    mock = MockLLM([
        f'{METH}\n{_bash(f)}\n{_write(f)}',
        f"done.\n{METH}",
    ])
    result = bouzecode(["go"], mock_llm=mock)
    assert _bash_saw_marker(result)


def test_no_false_positive_for_different_file(tmp_path):
    """Bash references a different file than the Write -> no dependency injected,
    so the referenced file genuinely does not exist when the Bash runs."""
    written = tmp_path / "temp_written.py"
    referenced = tmp_path / "temp_other.py"
    mock = MockLLM([
        f'{METH}\n{_bash(referenced)}\n{_write(written)}',
        f"done.\n{METH}",
    ])
    result = bouzecode(["go"], mock_llm=mock)
    assert not _bash_saw_marker(result)
    bash_out = "\n".join(_tool_results(result, "Bash"))
    assert "No such file" in bash_out or "can't open file" in bash_out


# ── edit auto-injection (Edit counts as a write for the basename map) ─────────

def test_edit_then_bash_runs_edit_first(tmp_path):
    """An Edit feeds the same write_map as Write: Bash referencing the edited
    file waits for the Edit. The Bash prints the post-edit content."""
    f = tmp_path / "temp_cfg.py"
    f.write_text('print("OLD")\n', encoding="utf-8")
    read = f'<tool_use name="Read" id="r1"><param name="file_path">{f}</param></tool_use>'
    discard = (f'<tool_use name="Snippet" id="s1"><param name="file_path">{f}</param>'
               f'<param name="discard">true</param></tool_use>')
    edit = (f'<tool_use name="Edit" id="e1"><param name="file_path">{f}</param>'
            f'<param name="old_string">OLD</param><param name="new_string">{MARKER}</param></tool_use>')
    bash = _bash(f, tid="b1")
    mock = MockLLM([
        f"{METH}\n{read}",                       # read first so Edit isn't blocked
        f"{METH}\n{discard}\n{edit}\n{bash}",    # Edit + Bash in one batch
        f"done.\n{METH}",
    ])
    result = bouzecode(["change it"], mock_llm=mock)
    assert _bash_saw_marker(result)
