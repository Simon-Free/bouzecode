# [desc] Conversation feature tests for Bash inline-python ban, Grep/Glob gitignore handling, and grep overflow summary. [/desc]
"""Search tool behaviour through real bouzecode() conversations.

Replaces the direct-call / subprocess-mocking unit tests (test_shell_ban,
test_gitignore_grep_glob, test_grep_summary): the (mocked) model issues Bash/Grep/
Glob tool calls and we assert on the tool results in the transcript. Boolean/array
params are coerced from XML by the tool registry (_coerce_params), so this exercises
the real path end to end.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _tool_result(call_xml, name, user="go"):
    # The closing response must be plain text with NO tool call: a meta-only
    # batch gets a continue-nudge instead of ending the conversation.
    mock = MockLLM([f"{METH}\n{call_xml}", "Done."])
    result = bouzecode([user], mock_llm=mock)
    msgs = [m for m in result.messages if m.get("role") == "tool" and m.get("name") == name]
    assert msgs, f"no {name} tool result in transcript"
    return msgs[0]["content"]


# ── Bash inline-python handling (spilled to a file, see test_shell_nesting_spill_e2e) ──

def test_bash_spills_inline_python_to_a_temp_file_instead_of_refusing():
    out = _tool_result(
        '<tool_use name="Bash" id="b1"><param name="command">python -c "print(1)"</param></tool_use>',
        "Bash",
    )
    assert "BLOCKED" not in out
    assert "temp_inline_" in out  # tells the agent where the code was written


def test_bash_allows_python_without_dash_c():
    out = _tool_result(
        '<tool_use name="Bash" id="b1"><param name="command">python --version</param></tool_use>',
        "Bash",
    )
    assert "BLOCKED" not in out


# ── Grep / Glob gitignore handling ───────────────────────────────────────────

@pytest.fixture
def git_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (proj / "code.py").write_text("TOKEN = 1\n", encoding="utf-8")
    (proj / "secret.log").write_text("TOKEN leaked\n", encoding="utf-8")
    return proj


def test_grep_respects_gitignore_by_default(git_project):
    out = _tool_result(
        f'<tool_use name="Grep" id="g1"><param name="pattern">TOKEN</param>'
        f'<param name="path">{git_project}</param></tool_use>',
        "Grep",
    )
    assert "code.py" in out
    assert "secret.log" not in out  # .gitignore'd file excluded by default


def test_grep_ignore_gitignore_false_includes_ignored(git_project):
    out = _tool_result(
        f'<tool_use name="Grep" id="g1"><param name="pattern">TOKEN</param>'
        f'<param name="path">{git_project}</param>'
        f'<param name="ignore_gitignore">false</param></tool_use>',
        "Grep",
    )
    assert "secret.log" in out  # now the ignored file is searched too


def test_glob_include_patterns_reincludes_ignored(git_project):
    out = _tool_result(
        f'<tool_use name="Glob" id="g1"><param name="pattern">**/*</param>'
        f'<param name="path">{git_project}</param>'
        f'<param name="include_patterns">["*.log"]</param></tool_use>',
        "Glob",
    )
    assert "secret.log" in out  # re-included despite .gitignore


# ── Grep overflow summary ────────────────────────────────────────────────────

@pytest.fixture
def big_grep_project(tmp_path):
    proj = tmp_path / "big"
    for d in ("agent", "tools", "web"):
        sub = proj / d
        sub.mkdir(parents=True)
        for i in range(20):
            body = "\n".join(f"NEEDLE_{j} = handle_NEEDLE(x)" for j in range(10))
            (sub / f"f{i}.py").write_text(body + "\n", encoding="utf-8")
    return proj


def test_grep_overflow_returns_structured_summary(big_grep_project):
    out = _tool_result(
        f'<tool_use name="Grep" id="g1"><param name="pattern">NEEDLE</param>'
        f'<param name="path">{big_grep_project}</param></tool_use>',
        "Grep",
    )
    assert "Grep overflow:" in out
    assert "matches in" in out and "files" in out  # match/file counts
    assert "By directory:" in out
    assert "Top files:" in out
    assert "Precise patterns:" in out              # NEEDLE_0.. share a prefix
    assert "Refine:" in out
    assert 'Grep(pattern=' in out                  # actionable refine suggestion
    assert "agent" in out and "tools" in out        # directory breakdown
    assert len(out) < 3000                          # budget-bounded, not the raw dump
