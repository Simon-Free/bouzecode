# [desc] Tests for _format_tool_call/_fmt_value (black-style multiline tool calls) and _is_failure. [/desc]
"""Tests for ui/tool_display tool-call rendering."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bouzecode.ui.tool_display import _format_tool_call, _fmt_value, _is_failure


# --- _fmt_value: repr with 100-char truncation via ellipsis ---

def test_fmt_value_short_string_keeps_quotes():
    assert _fmt_value("creating-agents") == '"creating-agents"'


def test_fmt_value_long_string_truncated_to_100_with_ellipsis():
    out = _fmt_value("x" * 150)
    assert out == '"' + "x" * 100 + '…"'


def test_fmt_value_non_string_uses_repr():
    assert _fmt_value(42) == "42"
    assert _fmt_value(["a", "b"]) == "['a', 'b']"


def test_fmt_value_long_non_string_truncated():
    out = _fmt_value(list(range(200)))
    assert out.endswith("…")
    assert len(out) == 101


# --- _format_tool_call: black-style multiline, every param shown ---

def test_empty_inputs_single_line():
    assert _format_tool_call("TaskList", {}) == "TaskList()"


def test_single_param_multiline():
    assert _format_tool_call("Skill", {"skill": "creating-agents"}) == (
        'Skill(\n    skill="creating-agents",\n)'
    )


def test_all_params_displayed_one_per_line():
    out = _format_tool_call("Methodology", {"content": "## Tache", "mode": "append"})
    assert out == (
        'Methodology(\n    content="## Tache",\n    mode="append",\n)'
    )


def test_long_value_truncated_with_ellipsis():
    out = _format_tool_call("Methodology", {"content": "x" * 200})
    assert "…" in out
    assert out.count("x") == 100


def test_tool_markup_in_values_neutralized():
    out = _format_tool_call("Bash", {"command": "echo <param>hi</param>"})
    assert "<param>" not in out
    assert "&lt;param&gt;" in out


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
