# [desc] Tests grep overflow summary generation, pattern extraction, and budget enforcement in shell_search module. [/desc]
"""Tests for grep overflow summary."""
from bouzecode.backend.tools.ops.shell_search import (
    _build_grep_summary, _extract_precise_patterns, _GREP_BUDGET,
)

SAMPLE_OUTPUT = "\n".join(
    f"src/agent/context.py:{i}:    thinking_block = extract_thinking(data)"
    for i in range(1, 51)
) + "\n" + "\n".join(
    f"src/tools/registry.py:{i}:    register_thinking_tool(name)"
    for i in range(10, 30)
) + "\n" + "\n".join(
    f"src/web/views.py:{i}:    thinking = req.get('thinking')"
    for i in range(5, 15)
)


def test_summary_under_budget():
    short = "src/foo.py:1: hello thinking world"
    result = _build_grep_summary(short, "thinking", "src/")
    assert "overflow" not in result.lower()
    assert "hello" in result


def test_summary_over_budget_has_structure():
    result = _build_grep_summary(SAMPLE_OUTPUT, "thinking", "src/")
    assert "Grep overflow:" in result
    assert "By directory:" in result
    assert "Top files:" in result
    assert "Preview:" in result
    assert "Refine:" in result


def test_summary_shows_match_count():
    result = _build_grep_summary(SAMPLE_OUTPUT, "thinking", "src/")
    assert "80 matches" in result
    assert "3 files" in result


def test_summary_respects_budget():
    big_output = "\n".join(
        f"src/mod{i // 100}/file{i}.py:{i}: token_handler = get_token_count(x)"
        for i in range(500)
    )
    result = _build_grep_summary(big_output, "token", "src/")
    assert len(result) < 3000


def test_summary_shows_directory_breakdown():
    result = _build_grep_summary(SAMPLE_OUTPUT, "thinking", "src/")
    assert "src/agent" in result or "src\\agent" in result
    assert "src/tools" in result or "src\\tools" in result


def test_summary_shows_refinement_suggestions():
    result = _build_grep_summary(SAMPLE_OUTPUT, "thinking", "src/")
    assert 'Grep(pattern="thinking"' in result


def test_extract_precise_patterns():
    matches = [
        ("f.py", 1, "get_thinking_blocks = extract_thinking(data)"),
        ("f.py", 2, "thinking_count += 1"),
        ("f.py", 3, "if thinking:"),
        ("g.py", 4, "register_thinking_tool(name)"),
        ("g.py", 5, "thinking_enabled = True"),
    ]
    result = _extract_precise_patterns(matches, "thinking")
    assert len(result) > 0
    assert all("thinking" in p.lower() for p in result)
    assert "thinking" not in [p.lower() for p in result]


def test_extract_precise_patterns_empty():
    matches = [("f.py", 1, "x = thinking")]
    result = _extract_precise_patterns(matches, "thinking")
    assert result == []


def test_precise_patterns_in_summary():
    output = "\n".join([
        "f.py:1: get_thinking_blocks(data)",
        "f.py:2: thinking_count += 1",
        "f.py:3: extract_thinking(x)",
        "g.py:4: register_thinking_tool()",
    ] * 100)
    result = _build_grep_summary(output, "thinking", ".")
    assert "Precise patterns:" in result
    assert "thinking_" in result.lower() or "extract_thinking" in result


def test_grep_budget_constant():
    assert _GREP_BUDGET == 1000
