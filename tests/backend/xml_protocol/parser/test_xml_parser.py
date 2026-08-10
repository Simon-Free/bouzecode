# [desc] Tests for incremental XML stream parser handling chunked tool_use blocks, CDATA, and edge cases. [/desc]
"""Tests for xml_tool_protocol.parser -- incremental XML stream parser."""
from __future__ import annotations


def _parser():
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    return XmlToolStreamParser()


def _feed(parser, chunk):
    """Compat helper: convert new list return to old (visible, completed) tuple."""
    items = parser.feed(chunk)
    visible = "".join(item for item in items if isinstance(item, str))
    completed = [item for item in items if isinstance(item, dict)]
    return visible, completed


def _tool(name, tid, **params):
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    px = ''.join(f'{po} name="{k}">{v}{pc}' for k, v in params.items())
    return f'{o} name="{name}" id="{tid}">{px}{c}'


def test_single_block_complete_in_one_chunk():
    p = _parser()
    xml = _tool("Read", "r1", file_path="a.py")
    visible, completed = _feed(p, xml)
    assert visible == ""
    assert len(completed) == 1
    assert completed[0] == {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}


def test_text_before_and_after_block():
    p = _parser()
    chunk = "Let me read the file.\n" + _tool("Read", "r1", file_path="a.py") + "\nDone."
    visible, completed = _feed(p, chunk)
    # Newlines hugging the (invisible) tool block are stripped by design.
    assert visible == "Let me read the file.Done."
    assert len(completed) == 1
    assert completed[0]["name"] == "Read"


def test_chunk_split_mid_opening_tag():
    p = _parser()
    full = _tool("Read", "r1", file_path="a.py")
    v1, c1 = _feed(p, full[:12])
    v2, c2 = _feed(p, full[12:])
    assert v1 == ""
    assert v2 == ""
    assert c1 == []
    assert len(c2) == 1


def test_chunk_split_mid_param_value():
    p = _parser()
    full = _tool("Write", "w1", content="def foo():\n    pass", file_path="a.py")
    split_at = full.index("def fo") + 6
    v1, c1 = _feed(p, full[:split_at])
    v2, c2 = _feed(p, full[split_at:])
    assert c1 == []
    assert len(c2) == 1
    assert c2[0]["name"] == "Write"
    assert c2[0]["input"]["content"] == "def foo():\n    pass"
    assert c2[0]["input"]["file_path"] == "a.py"


def test_chunk_split_mid_closing_tag():
    p = _parser()
    full = _tool("Read", "r1", file_path="a.py")
    v1, c1 = _feed(p, full[:-2])
    v2, c2 = _feed(p, full[-2:])
    assert c1 == []
    assert len(c2) == 1
    assert c2[0]["input"]["file_path"] == "a.py"


def test_text_chunks_visible_incrementally():
    p = _parser()
    v1, _ = _feed(p, "Hello ")
    v2, _ = _feed(p, "world.")
    assert v1 == "Hello "
    assert v2 == "world."


def test_cdata_with_lt_gt_amp():
    p = _parser()
    code = "if a < b and c > 0: pass"
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    cdo = "<!" + "[CDATA["
    cdc = "]" + "]>"
    xml = (
        f'{o} name="Write" id="w1">'
        f'{po} name="content">{cdo}{code}{cdc}{pc}'
        f'{c}'
    )
    _, completed = _feed(p, xml)
    assert completed[0]["input"]["content"] == code


def test_multiple_blocks_in_one_feed():
    p = _parser()
    xml = _tool("Read", "r1", file_path="a.py") + _tool("Read", "r2", file_path="b.py") + _tool("Read", "r3", file_path="c.py")
    _, completed = _feed(p, xml)
    assert len(completed) == 3
    assert [c["id"] for c in completed] == ["r1", "r2", "r3"]
    assert [c["input"]["file_path"] for c in completed] == ["a.py", "b.py", "c.py"]


def test_multiple_blocks_interleaved_with_text():
    p = _parser()
    xml = "First, I will read a.py.\n" + _tool("Read", "r1", file_path="a.py") + "\nThen b.py.\n" + _tool("Read", "r2", file_path="b.py")
    visible, completed = _feed(p, xml)
    assert "First, I will read a.py." in visible
    assert "Then b.py." in visible
    assert len(completed) == 2


def test_param_value_empty_string():
    p = _parser()
    xml = _tool("Bash", "b1", command="")
    _, completed = _feed(p, xml)
    assert completed[0]["input"]["command"] == ""


def test_no_params():
    p = _parser()
    xml = "<" + 'tool_use name="ListAgentTasks" id="l1">' + "</" + 'tool_use>'
    _, completed = _feed(p, xml)
    assert completed[0] == {"id": "l1", "name": "ListAgentTasks", "input": {}}


def test_unclosed_block_finalize_emits_error():
    p = _parser()
    partial = _tool("Read", "r1", file_path="a.py")
    v, c = _feed(p, partial[:-12])
    assert c == []
    leftover = p.finalize()
    assert len(leftover) == 1
    assert leftover[0]["name"] == "_XmlParseError"
    assert "_error" in leftover[0]["input"]


def test_malformed_attribute_emits_error():
    p = _parser()
    xml = "<" + "tool_use name=broken no quotes>" + "</" + "tool_use>" 
    v, c = _feed(p, xml)
    assert len(c) == 1
    assert c[0]["name"] == "_XmlParseError"
    v2, c2 = _feed(p, _tool("Read", "r1", file_path="a.py"))
    assert len(c2) == 1
    assert c2[0]["name"] == "Read"


def test_missing_name_emits_error():
    p = _parser()
    xml = "<" + 'tool_use id="x1">' + "<" + 'param name="file_path">a.py' + "</" + "param>" + "</" + "tool_use>" 
    _, c = _feed(p, xml)
    assert len(c) == 1
    assert c[0]["name"] == "_XmlParseError"
    assert "name" in c[0]["input"]["_error"].lower()


def test_unknown_param_still_captured():
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    xml = (
        f'{o} name="Read" id="r1">'
        f'{po} name="file_path">a.py{pc}'
        f'{po} name="not_a_real_param">whatever{pc}'
        f'{c}'
    )
    _, c = _feed(p, xml)
    assert c[0]["name"] == "Read"
    assert c[0]["input"]["not_a_real_param"] == "whatever"


def test_single_quotes_attributes():
    p = _parser()
    xml = "<" + "tool_use name='Read' id='r1'>" + "<" + "param name='file_path'>a.py" + "</" + "param>" + "</" + "tool_use>" 
    _, completed = _feed(p, xml)
    assert completed[0] == {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}


def test_tool_call_alias_is_a_regular_param():
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    xml = (
        f'{o} name="Read" id="r1">'
        f'{po} name="file_path">a.py{pc}'
        f'{po} name="tool_call_alias">r1{pc}'
        f'{c}'
    )
    _, completed = _feed(p, xml)
    assert completed[0]["input"]["tool_call_alias"] == "r1"
    assert completed[0]["input"]["file_path"] == "a.py"


def test_streamed_one_char_at_a_time():
    p = _parser()
    xml = _tool("Read", "r1", file_path="a.py")
    all_completed = []
    all_visible = []
    for ch in xml:
        v, c = _feed(p, ch)
        all_visible.append(v)
        all_completed.extend(c)
    assert "".join(all_visible) == ""
    assert len(all_completed) == 1
    assert all_completed[0]["input"] == {"file_path": "a.py"}


def test_id_missing_is_still_parsed():
    p = _parser()
    xml = "<" + 'tool_use name="Read">' + "<" + 'param name="file_path">a.py' + "</" + "param>" + "</" + "tool_use>" 
    _, completed = _feed(p, xml)
    assert len(completed) == 1
    assert completed[0]["name"] == "Read"
    assert completed[0]["input"] == {"file_path": "a.py"}


def test_text_with_angle_bracket_not_tool():
    p = _parser()
    v, c = _feed(p, "if a < b then proceed. ")
    assert v == "if a < b then proceed. "
    assert c == []


def test_xml_parse_error_executor_returns_diagnostic():
    from bouzecode.backend.core.tool_registry import execute_tool
    result = execute_tool(
        "_XmlParseError",
        {"_error": "unclosed block at end of stream", "_source": "partial xml"},
        {},
    )
    assert "unclosed" in result.lower()


def test_xml_parse_error_auto_permitted():
    from bouzecode.backend.agent import _check_permission
    tc = {"name": "_XmlParseError", "input": {"_error": "x"}, "id": "e1"}
    assert _check_permission(tc, {"permission_mode": "auto"}) is True


def test_trailing_newlines_before_tool_stripped():
    """Parasitic newlines between text and tool blocks should be stripped."""
    p = _parser()
    chunk = "Phase 1: READ\n\n\n\n\n\n\n\n" + _tool("Read", "r1", file_path="a.py")
    visible, completed = _feed(p, chunk)
    assert visible == "Phase 1: READ"
    assert len(completed) == 1


def test_inter_tool_newlines_stripped():
    """Newlines between consecutive tool blocks should not appear as visible text."""
    p = _parser()
    chunk = _tool("Read", "r1", file_path="a.py") + "\n\n" + _tool("Read", "r2", file_path="b.py")
    visible, completed = _feed(p, chunk)
    assert visible == ""
    assert len(completed) == 2


def test_held_back_newlines_stripped_when_tool_follows():
    """Trailing newlines held back in one chunk get stripped when next chunk is a tool."""
    p = _parser()
    v1, c1 = _feed(p, "Some text.\n\n\n")
    assert v1 == "Some text."
    assert c1 == []
    v2, c2 = _feed(p, _tool("Read", "r1", file_path="a.py"))
    assert v2 == ""
    assert len(c2) == 1


def test_held_back_newlines_emitted_when_text_follows():
    """Trailing newlines held back get emitted when followed by normal text."""
    p = _parser()
    v1, _ = _feed(p, "First.\n\n")
    assert v1 == "First."
    v2, _ = _feed(p, "Second.")
    assert v2 == "\n\nSecond."


def test_inline_backticked_tool_use_partial_word_is_visible():
    """'<tool_used' or '<tool_user' (no whitespace/`>` after the 9 chars) is literal prose."""
    p = _parser()
    v, c = _feed(p, "Fixing the <tool_used flag and also <tool_user handling.")
    assert c == []
    assert v == "Fixing the <tool_used flag and also <tool_user handling."


def test_tool_use_open_without_terminator_is_held_then_resolved_as_literal():
    """Streaming: '<tool_use' arrives alone, next chunk reveals it's '<tool_used'."""
    p = _parser()
    v1, c1 = _feed(p, "prefix <tool_use")
    assert c1 == []
    assert v1 == "prefix "
    v2, c2 = _feed(p, "d to describe. ")
    assert c2 == []
    assert v2 == "<tool_used to describe. "


def test_tool_use_open_followed_by_gt_is_prose_not_a_call():
    """'<tool_use></tool_use>' names no tool and holds no param: it is the model
    quoting the tag, so it stays visible text instead of costing an error round-trip."""
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    visible, completed = _feed(p, f"{o}>{c}")
    assert completed == []
    assert visible == f"{o}>{c}"


def test_bare_nested_tool_use_inside_param_value_does_not_break_outer():
    """Edit new_string contains a bare <tool_use>...</tool_use> (no CDATA).
    The outer framing must still close on its own </tool_use>, not the inner one."""
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    inner = f'{o} name="Read" id="r1">{po} name="file_path">a.py{pc}{c}'
    outer = f'{o} name="Edit" id="e1">{po} name="new_string">prefix {inner} suffix{pc}{c}'
    visible, completed = _feed(p, outer)
    assert visible == ""
    assert len(completed) == 1
    assert completed[0]["name"] == "Edit"
    assert completed[0]["id"] == "e1"
    assert completed[0]["input"]["new_string"] == f"prefix {inner} suffix"


def test_bare_close_tag_inside_param_value_does_not_close_outer():
    """Param value with a raw </tool_use> must not close the outer tool_use early."""
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    payload = f"line1\n{c}\nline2"
    outer = f'{o} name="Write" id="w1">{po} name="content">{payload}{pc}{c}'
    _, completed = _feed(p, outer)
    assert len(completed) == 1
    assert completed[0]["name"] == "Write"
    assert completed[0]["input"]["content"] == payload


def test_depends_on_bracket_syntax_in_attributes():
    """depends_on=["wp1"] in opening tag must be parsed, not rejected."""
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    xml = (
        f'{o} name="Write" id="w1" tool_call_alias="w1" depends_on=["wp1"]>'
        f'{po} name="file_path">a.py{pc}'
        f'{po} name="content">hello{pc}'
        f'{c}'
    )
    _, completed = _feed(p, xml)
    assert len(completed) == 1
    assert completed[0]["name"] == "Write"
    assert completed[0]["input"]["file_path"] == "a.py"
    assert completed[0]["input"]["tool_call_alias"] == "w1"
    assert completed[0]["input"]["depends_on"] == '["wp1"]'


def test_depends_on_multiple_bracket_syntax():
    """depends_on=["w1","w2"] with multiple deps must parse correctly."""
    p = _parser()
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    xml = (
        f'{o} name="Bash" id="b1" depends_on=["w1","w2"]>'
        f'{po} name="command">echo hi{pc}'
        f'{c}'
    )
    _, completed = _feed(p, xml)
    assert len(completed) == 1
    assert completed[0]["name"] == "Bash"
    assert completed[0]["input"]["depends_on"] == '["w1","w2"]'


def test_unescaped_cdata_terminator_in_payload_preserved():
    payload = 'return blocks\n]]' + '>'
    o = "<" + "tool_use"
    c = "</" + "tool_use>"
    po = "<" + "param"
    pc = "</" + "param>"
    cdo = "<!" + "[CDATA["
    cdc = "]" + "]>"
    raw = f'{o} name="Write" id="w1">{po} name="content">{cdo}{payload}{cdc}{pc}{c}'
    p = _parser()
    visible, completed = _feed(p, raw)
    assert visible == ""
    assert len(completed) == 1
    assert completed[0]["input"]["content"] == payload


def test_interleaved_order():
    """Verify that feed() returns text and tools in correct interleaved order."""
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    p = XmlToolStreamParser()
    chunk = "Let me read the file.\n" + _tool("Read", "r1", file_path="a.py") + "\nDone."
    items = p.feed(chunk)
    # Should be: [text_before, tool, text_after] in order
    assert len(items) == 3
    assert isinstance(items[0], str)
    assert items[0] == "Let me read the file."
    assert isinstance(items[1], dict)
    assert items[1]["name"] == "Read"
    assert isinstance(items[2], str)
    assert items[2] == "Done."


def test_interleaved_multiple_tools():
    """Multiple tools with text between them maintain correct order."""
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    p = XmlToolStreamParser()
    chunk = (
        "First task\n"
        + _tool("Read", "r1", file_path="a.py")
        + "\nSecond task\n"
        + _tool("Write", "w1", file_path="b.py", content="hello")
        + "\nAll done."
    )
    items = p.feed(chunk)
    assert len(items) == 5
    assert items[0] == "First task"
    assert items[1]["name"] == "Read"
    assert items[2] == "Second task"
    assert items[3]["name"] == "Write"
    assert items[4] == "All done."
