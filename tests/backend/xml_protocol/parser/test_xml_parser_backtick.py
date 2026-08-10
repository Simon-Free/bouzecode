# [desc] Tests that XML parser correctly skips tool_use elements inside backtick-wrapped code regions. [/desc]
"""Tests for xml_tool_protocol.parser — backtick code region handling."""
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


# --- Fenced code blocks ---

def test_fenced_block_tool_use_is_visible():
    """<tool_use inside a ```fenced block should be visible text, not parsed."""
    p = _parser()
    fence = '```xml\n' + _tool("Read", "r1", file_path="a.py") + '\n```'
    chunk = "Example:\n" + fence + "\nDone."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "Example:" in visible
    assert "Done." in visible
    assert "<tool_use" in visible


def test_fenced_block_followed_by_real_tool():
    """Real tool after a fenced block must still be parsed."""
    p = _parser()
    fence = '```xml\n' + _tool("Read", "r1", file_path="fake.py") + '\n```'
    real = _tool("Write", "w1", file_path="real.py", content="hi")
    chunk = "Example:\n" + fence + "\n" + real
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Write"
    assert completed[0]["input"]["file_path"] == "real.py"
    assert "Example:" in visible
    assert "<tool_use" in visible  # the fenced one is visible


def test_fenced_block_streaming_across_chunks():
    """Fence opens in one chunk, tool_use arrives in next, fence closes in third."""
    p = _parser()
    v1, c1 = _feed(p, "Here:\n```xml\n")
    assert c1 == []
    v2, c2 = _feed(p, _tool("Read", "r1", file_path="a.py"))
    assert c2 == []
    v3, c3 = _feed(p, "\n```\nAfter.")
    assert c3 == []
    # All content should be visible
    full_visible = v1 + v2 + v3
    assert "<tool_use" in full_visible
    assert "After." in full_visible


def test_fenced_block_streaming_then_real_tool():
    """Fence in first chunks, real tool after fence closes."""
    p = _parser()
    v1, c1 = _feed(p, "Code:\n```\nfake ")
    assert c1 == []
    v2, c2 = _feed(p, _tool("Read", "r1", file_path="fake.py") + "\n```\n")
    assert c2 == []
    v3, c3 = _feed(p, _tool("Write", "w1", file_path="real.py", content="x"))
    assert len(c3) == 1
    assert c3[0]["name"] == "Write"


def test_multiple_fences_in_one_chunk():
    """Multiple fenced blocks each containing tool_use, followed by real tool."""
    p = _parser()
    fence1 = '```\n' + _tool("Read", "r1", file_path="a.py") + '\n```'
    fence2 = '```\n' + _tool("Write", "w1", file_path="b.py", content="x") + '\n```'
    real = _tool("Bash", "b1", command="echo hi")
    chunk = fence1 + "\n" + fence2 + "\n" + real
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Bash"


# --- Inline backticks (double) ---

def test_inline_double_backtick_tool_use_is_visible():
    """<tool_use inside `` is visible text, not parsed."""
    p = _parser()
    chunk = "Use ``" + _tool("Read", "r1", file_path="a.py") + "`` to read files."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "<tool_use" in visible
    assert "to read files." in visible


def test_inline_double_backtick_followed_by_real_tool():
    """Real tool after inline backtick example."""
    p = _parser()
    example = "``" + _tool("Read", "r1", file_path="fake.py") + "``"
    real = _tool("Write", "w1", file_path="real.py", content="hi")
    chunk = "Example: " + example + "\n" + real
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Write"
    assert "Example:" in visible


def test_inline_triple_backtick_not_at_line_start():
    """``` not at line start is inline code, not a fence."""
    p = _parser()
    chunk = "Use ```" + _tool("Read", "r1", file_path="a.py") + "``` for tools."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "<tool_use" in visible


def test_inline_backtick_streaming():
    """Inline code split across chunks holds back properly."""
    p = _parser()
    v1, c1 = _feed(p, "Use ``<tool_use")
    # Should hold back — unclosed inline code with potential tool
    assert c1 == []
    v2, c2 = _feed(p, ' name="Read" id="r1">`` ok.')
    assert c2 == []
    full = v1 + v2
    assert "<tool_use" in full
    assert "ok." in full


# --- Single backtick does NOT trigger code detection ---

def test_single_backtick_does_not_protect():
    """A single backtick should NOT prevent tool parsing (too many false positives)."""
    p = _parser()
    # Single backtick before a real tool should not interfere
    chunk = "It's a `test`.\n" + _tool("Read", "r1", file_path="a.py")
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Read"


# --- Edge cases ---

def test_fence_without_tool_use_passes_through():
    """Fenced block without any tool_use is just normal visible text."""
    p = _parser()
    chunk = "```python\ndef foo():\n    pass\n```\nDone."
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "def foo():" in visible
    assert "Done." in visible


def test_unclosed_fence_at_finalize():
    """Unclosed fence at end of stream should not produce an error."""
    p = _parser()
    chunk = "```xml\n<tool_use"
    v, c = _feed(p, chunk)
    assert c == []
    errors = p.finalize()
    assert errors == []


def test_real_tool_before_fence():
    """Real tool before a fenced block is parsed normally."""
    p = _parser()
    real = _tool("Read", "r1", file_path="a.py")
    fence = '```\n' + _tool("Write", "w1", file_path="fake.py", content="x") + '\n```'
    chunk = real + "\nExample:\n" + fence
    visible, completed = _feed(p, chunk)
    assert len(completed) == 1
    assert completed[0]["name"] == "Read"
    assert "Example:" in visible


def test_fence_with_language_tag():
    """Fenced block with language tag (```xml) is handled."""
    p = _parser()
    chunk = '```xml\n' + _tool("Read", "r1", file_path="a.py") + '\n```'
    visible, completed = _feed(p, chunk)
    assert completed == []
    assert "<tool_use" in visible


def test_is_in_code_helper_direct():
    """Direct test of _is_in_code helper function."""
    from bouzecode.backend.xml_tool_protocol.parser import _is_in_code

    # Not in code
    buf = "hello <tool_use world"
    assert _is_in_code(buf, 6) is None

    # Inside fenced block
    buf = "```\n<tool_use\n```\nafter"
    result = _is_in_code(buf, 4)
    assert result is not None
    skip_to, region_start, is_fence = result
    assert is_fence is True
    assert skip_to > 4
    assert region_start == 0

    # Inside inline double backtick
    buf = "use ``<tool_use`` rest"
    result = _is_in_code(buf, 6)
    assert result is not None
    skip_to, region_start, is_fence = result
    assert is_fence is False
    assert skip_to > 6
    assert region_start == 4

    # Single backtick — NOW in code (threshold lowered to 1)
    buf = "a `<tool_use` b"
    result = _is_in_code(buf, 3)
    assert result is not None
    skip_to, region_start, is_fence = result
    assert is_fence is False
    assert region_start == 2


def test_has_unclosed_fence_helper():
    """Direct test of _has_unclosed_fence helper."""
    from bouzecode.backend.xml_tool_protocol.parser import _has_unclosed_fence

    assert _has_unclosed_fence("no fence here") is False
    assert _has_unclosed_fence("```\ncode\n```") is False
    assert _has_unclosed_fence("```\ncode") is True
    assert _has_unclosed_fence("```\ncode\n```\n```\nmore") is True
    assert _has_unclosed_fence("text\n```\ncode\n```") is False
