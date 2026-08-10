# [desc] Tests for ui/tool_display: _format_tool_call rendering and _is_failure error detection. [/desc]
"""`_format_tool_call` rendering + `_is_failure` classification.

`_tool_desc` is gone. It rendered a one-line, per-tool SUMMARY (Methodology
snippets collapsed to "2 snippets: a.py L1-10", a label for synthetic error
tools). The display now shows the call VERBATIM in a black-style multiline
block, every parameter included, with only long values truncated — a deliberate
change of contract, not a rename. The Methodology-summary tests were dropped
with the behaviour they described; what is pinned below is the new contract.
"""
from __future__ import annotations

from bouzecode.ui.tool_display import _format_tool_call, _is_failure


# --- _format_tool_call: every param, one per line, black style ---------------

def test_no_input_renders_on_a_single_line():
    assert _format_tool_call("GetDiff", {}) == "GetDiff()"


def test_single_param_is_quoted_and_indented():
    assert _format_tool_call("Read", {"file_path": "/repo/a.py"}) == (
        'Read(\n    file_path="/repo/a.py",\n)'
    )


def test_every_param_is_shown_not_just_the_first():
    rendered = _format_tool_call("Grep", {"pattern": "handler", "path": "/repo", "context": 2})
    assert 'pattern="handler"' in rendered
    assert 'path="/repo"' in rendered
    assert "context=2" in rendered


def test_non_string_values_keep_their_repr():
    rendered = _format_tool_call("Snippet", {"ranges": [[1, 10]], "discard": True})
    assert "ranges=[[1, 10]]" in rendered
    assert "discard=True" in rendered


def test_long_string_value_is_truncated_with_an_ellipsis():
    rendered = _format_tool_call("Methodology", {"content": "x" * 200})
    assert "…" in rendered
    assert rendered.count("x") == 100


def test_long_non_string_value_is_truncated_too():
    rendered = _format_tool_call("Bash", {"env": list(range(200))})
    assert "…" in rendered
    assert len(rendered.splitlines()[1]) < 140


def test_inline_tool_markup_in_a_value_is_neutralized():
    """A param echoing tool-call XML must not be re-emitted as live markup."""
    rendered = _format_tool_call(
        "Write", {"content": '<tool_use name="Read" id="r1"></tool_use>'})
    assert "<tool_use name=" not in rendered
    assert "</tool_use>" not in rendered


# --- _is_failure: error results must render as failures regardless of case ---

def test_xml_parse_error_uppercase_is_failure():
    # Regression: the registry diagnostic starts with "ERROR" (uppercase), which
    # the old result.startswith("Error") check missed → rendered as green success.
    assert _is_failure("_XmlParseError", "ERROR parsing your tool call XML: ...")


def test_synthetic_error_tools_always_fail_even_with_odd_result():
    for name in ("_XmlParseError", "_InvalidToolName", "_ToolArgsParseError"):
        assert _is_failure(name, "")


def test_plain_error_and_denied_are_failures():
    assert _is_failure("Grep", "Error: no matches")
    assert _is_failure("Bash", "Denied by user")
    assert _is_failure("Bash", "  ERROR: boom")  # leading whitespace + uppercase


def test_successful_result_is_not_failure():
    assert not _is_failure("Grep", "src/a.py\nsrc/b.py")
    assert not _is_failure("Read", "     1\tcontent")
