# [desc] Conversation tests: a nested `powershell -Command` wrapper is unwrapped (or deliberately kept), and inline `python -c` is spilled to a temp script instead of refused. [/desc]
"""Bash shell-layer behaviour through real bouzecode() conversations.

The (mocked) model issues Bash calls and we read the tool result in the
transcript. Commands really run — mocking the shell would prove nothing here.

Two behaviours are covered:
  - the Bash tool already IS PowerShell, so a `powershell -Command "..."` wrapper
    written by the model is a second shell that eats the body's variables before
    the inner shell sees them; it is unwrapped, unless the wrapper carries a flag
    that means the nesting was deliberate;
  - `python -c "<code>"` is no longer refused: the code is written to a
    `temp_*.py` file whose path is reported, and that file is run.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the Bash tool only runs PowerShell on win32"
)


def bash(command: str) -> str:
    """Let the agent run `command` through the Bash tool; return the tool result."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1">'
        f'<param name="command">{command}</param></tool_use>',
        "Done.",  # plain text, no tool call: that is what ends the conversation
    ])
    result = bouzecode(["run it"], mock_llm=mock)
    results = [m for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert results, "no Bash tool result in the transcript"
    return results[0]["content"]


@pytest.fixture(autouse=True)
def own_scratch_session(request):
    """Give each conversation its own scratch session, as a real run has — else a
    parallel test's end-of-session cleanup deletes the file we just spilled."""
    from bouzecode.backend.tools.ops.scratch import cleanup_scratch, set_scratch_session
    set_scratch_session(f"test_{request.node.name}")
    yield
    cleanup_scratch()
    set_scratch_session(None)


@pytest.fixture
def three_line_file(tmp_path) -> Path:
    path = tmp_path / "lines.txt"
    path.write_text("un\ndeux\ntrois\n", encoding="utf-8")
    return path


# ── The wrapper the model keeps writing is unwrapped ──────────────────────────

@windows_only
def test_nested_powershell_expands_env_var_once_and_returns_its_value():
    out = bash('powershell -Command "echo $env:USERNAME"')
    assert os.environ["USERNAME"] in out


@windows_only
def test_nested_powershell_no_longer_eats_the_variables_of_its_own_body(three_line_file):
    """The wrapper used to interpolate $f away, leaving the child `='...'; (Get-Content )`."""
    out = bash(f"""powershell -NoProfile -Command "$f='{three_line_file}'; (Get-Content $f).Count\"""")
    assert "3" in out
    assert "CommandNotFoundException" not in out


@windows_only
def test_same_command_without_the_wrapper_gives_the_same_answer(three_line_file):
    out = bash(f"$f='{three_line_file}'; (Get-Content $f).Count")
    assert "3" in out


@windows_only
def test_a_plain_command_is_left_untouched():
    out = bash("Write-Output bonjour")
    assert "bonjour" in out


# ── Wrappers that must survive: unwrapping them would change behaviour ────────

# The body below prints RAN only if it is EVALUATED: the literal never appears in
# the command text, so finding it in the output proves the body really executed.
RAN_ONLY_IF_EVALUATED = "$m='R'+'AN'; Write-Output $m"


@windows_only
def test_the_same_body_does_run_when_the_wrapper_is_a_plain_one():
    out = bash(f'powershell -Command "{RAN_ONLY_IF_EVALUATED}"')
    assert "RAN" in out


@windows_only
def test_execution_policy_wrapper_is_kept_because_it_is_deliberate():
    """-ExecutionPolicy changes what the child is allowed to run, so the wrapper
    stays: the body keeps being eaten by the outer shell, exactly as before."""
    out = bash(f'powershell -ExecutionPolicy Bypass -Command "{RAN_ONLY_IF_EVALUATED}"')
    assert "RAN" not in out
    assert "CommandNotFoundException" in out  # the child got the emptied body


@windows_only
def test_pwsh_wrapper_is_kept_because_it_is_another_runtime():
    """pwsh is PowerShell 7, not the 5.1 host we run in — never flatten it.
    Installed or not, an unwrapped body would have printed RAN."""
    out = bash(f'pwsh -Command "{RAN_ONLY_IF_EVALUATED}"')
    assert "RAN" not in out


# ── Inline python is spilled to a file instead of being refused ───────────────

def test_inline_python_runs_and_reports_where_it_was_written():
    out = bash('python -c "print(1+1)"')
    assert "BLOCKED" not in out
    assert "2" in out
    spilled = re.search(r"(\S+temp_inline_\w+\.py)", out)
    assert spilled, f"the spilled script path is not reported: {out!r}"
    assert "print(1+1)" in Path(spilled.group(1)).read_text(encoding="utf-8")


def test_inline_python_in_a_pipeline_is_spilled_too():
    out = bash('echo ignore | python -c "print(6*7)"')
    assert "42" in out
    assert "temp_inline_" in out


def test_running_a_python_script_file_is_left_alone(tmp_path):
    script = tmp_path / "temp_script.py"
    script.write_text("print('from the file')\n", encoding="utf-8")
    out = bash(f'python "{script}"')
    assert "from the file" in out
    assert "temp_inline_" not in out  # nothing to spill: it already is a file


def test_unquoted_inline_python_is_still_refused():
    """Nothing to extract losslessly here, so the old actionable refusal stands."""
    out = bash("python -c print(1)")
    assert "BLOCKED" in out
    assert "temp_" in out and "Write" in out
