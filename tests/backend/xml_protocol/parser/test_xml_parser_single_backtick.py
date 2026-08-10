# [desc] Tests that XML tool_use tags inside backticks and indented code blocks are not parsed as real tools [/desc]
"""Tests for xml_tool_protocol.parser — single backtick and indented code block handling."""
from __future__ import annotations

def _feed(parser, chunk):
    """Compat helper: convert new list return to old (visible, completed) tuple."""
    items = parser.feed(chunk)
    visible = "".join(item for item in items if isinstance(item, str))
    completed = [item for item in items if isinstance(item, dict)]
    return visible, completed




def _parser():
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    return XmlToolStreamParser()


def _tool(name, tid, **params):
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    px = ''.join(f'{po} name="{k}">{v}{pc}' for k, v in params.items())
    return f'{o} name="{name}" id="{tid}">{px}{c}'


# --- Single backtick inline code ---

def test_single_backtick_tool_use_not_parsed():
    """<tool_use inside single backticks should be visible text, not parsed."""
    p = _parser()
    chunk = "Use `" + _tool("Read", "r1", file_path="a.py") + "` to read files."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "Use `" in visible
    assert "<tool_use" in visible or "tool_use" in visible


def test_single_backtick_multiple_regions():
    """Multiple single-backtick regions each protect their content."""
    p = _parser()
    t1 = _tool("Read", "r1", file_path="a.py")
    t2 = _tool("Write", "w1", file_path="b.py", content="x")
    chunk = f"First `{t1}` and second `{t2}` done."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "First" in visible
    assert "done." in visible


def test_single_backtick_with_real_tool_after():
    """Single backtick code followed by a real tool call → only real tool is parsed."""
    p = _parser()
    example = "`" + _tool("Read", "r1", file_path="fake.py") + "`"
    real = _tool("Write", "w1", file_path="real.py", content="hi")
    chunk = f"Example: {example}\n{real}"
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Write"
    assert completed[0]["input"]["file_path"] == "real.py"
    assert "Example:" in visible


def test_single_backtick_streaming_across_chunks():
    """Single backtick opens in one chunk, tool_use arrives in next chunk."""
    p = _parser()
    v1, c1 = _feed(p, "Use `")
    assert c1 == []
    tool_text = _tool("Read", "r1", file_path="a.py")
    v2, c2 = _feed(p, tool_text + "` to read.")
    assert c2 == []
    # The tool_use should NOT have been parsed
    final_visible = v1 + v2
    assert "Use `" in final_visible or "Use" in final_visible


def test_unmatched_single_backtick_protects_following():
    """An unmatched single backtick at end protects following content (unclosed code span)."""
    p = _parser()
    v1, c1 = _feed(p, "Here is `some code with ")
    assert c1 == []
    tool_text = _tool("Read", "r1", file_path="a.py")
    v2, c2 = _feed(p, tool_text)
    # Should not parse as tool since we're inside unclosed backtick
    assert c2 == []


# --- Indented code blocks (4 spaces) ---

def test_indented_code_block_tool_use_not_parsed():
    """<tool_use inside a 4-space indented code block should be visible text."""
    p = _parser()
    tool_text = _tool("Read", "r1", file_path="a.py")
    chunk = f"Example:\n\n    {tool_text}\n\nDone."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "Example:" in visible
    assert "Done." in visible


def test_tab_indented_code_block_not_parsed():
    """<tool_use inside a tab-indented code block should be visible text."""
    p = _parser()
    tool_text = _tool("Read", "r1", file_path="a.py")
    chunk = f"Example:\n\n\t{tool_text}\n\nDone."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "Done." in visible


def test_indented_block_followed_by_real_tool():
    """Indented code block followed by real tool → only real tool parsed."""
    p = _parser()
    fake = _tool("Read", "r1", file_path="fake.py")
    real = _tool("Write", "w1", file_path="real.py", content="hi")
    chunk = f"Example:\n\n    {fake}\n\n{real}"
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Write"
    assert "Example:" in visible


# --- Regression: real tools still work ---

def test_real_tool_still_parsed():
    """A normal tool call outside any code region is still parsed correctly."""
    p = _parser()
    real = _tool("Read", "r1", file_path="test.py")
    chunk = f"I'll read the file now.\n{real}"
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Read"
    assert completed[0]["input"]["file_path"] == "test.py"


def test_double_backtick_still_works():
    """Double backtick inline code still protects (regression)."""
    p = _parser()
    tool_text = _tool("Read", "r1", file_path="a.py")
    chunk = f"Use ``{tool_text}`` to read."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "Use ``" in visible or "Use" in visible
