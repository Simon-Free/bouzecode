# [desc] Tests for ui/tool_display _tool_desc formatting and _is_failure error detection logic
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests for ui/tool_display _tool_desc formatting and _is_failure error detection logic</param></tool_use> [/desc]
"""Tests for ui/tool_display _tool_desc descriptions."""
from __future__ import annotations

from bouzecode.ui.tool_display import _tool_desc, _is_failure


def test_methodology_content_only():
    desc = _tool_desc("Methodology", {"content": "locked on dispatch path"})
    assert desc == 'Methodology(content="locked on dispatch path")'


def test_methodology_content_truncated_with_ellipsis():
    long = "x" * 200
    desc = _tool_desc("Methodology", {"content": long})
    assert "…" in desc
    assert desc.count("x") == 60


def test_methodology_snippets_only_shows_file_and_ranges():
    desc = _tool_desc("Methodology", {"snippets": [
        {"file_path": "C:/repo/azure_fs.py", "ranges": [[80, 95], [210, 225]]},
        {"file_path": "/unix/path/dispatch.py", "ranges": [[1, 40]]},
    ]})
    assert "2 snippets:" in desc
    assert "azure_fs.py L80-95+L210-225" in desc
    assert "dispatch.py L1-40" in desc


def test_methodology_content_and_snippets_shown_together():
    desc = _tool_desc("Methodology", {
        "content": "editing download_directory_azcopy",
        "snippets": [{"file_path": "C:/a.py", "ranges": [[1, 10]]}],
    })
    assert 'content="editing download_directory_azcopy"' in desc
    assert "1 snippets: a.py L1-10" in desc


def test_methodology_replace_mode_tagged():
    desc = _tool_desc("Methodology", {"content": "reset", "mode": "replace"})
    assert desc.endswith("[replace]")


def test_methodology_more_than_three_snippets_shows_plus_count():
    desc = _tool_desc("Methodology", {"snippets": [
        {"file_path": f"/a{i}.py", "ranges": [[1, 5]]} for i in range(5)
    ]})
    assert "5 snippets:" in desc
    assert "+2 more" in desc


def test_methodology_empty_inputs_not_crashing():
    desc = _tool_desc("Methodology", {})
    assert desc == "Methodology(empty)"


def test_unknown_tool_falls_back_to_first_input():
    desc = _tool_desc("SomeOtherTool", {"arg": "value"})
    assert desc == "SomeOtherTool(['value'])"


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


def test_synthetic_error_tool_has_clear_label():
    assert _tool_desc("_XmlParseError", {"_error": "no <param>"}) == \
        "Malformed tool call (invalid XML)"
