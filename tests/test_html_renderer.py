# [desc] Tests for html_renderer: text parsing, JSON parsing, and rendering to HTML.
"""Tests for html_renderer parser, json_parser, and renderer."""
from html_renderer.parser import AssistantText, ToolCall, ToolResult, UserMessage, parse_session
from html_renderer.json_parser import parse_session_json
from html_renderer.renderer import render_html


SESSION_SIMPLE = """\
Hello world.

<tool_use name="Read" id="r1"><param name="file_path">/tmp/a.txt</param></tool_use>

<tool_result id="r1">file content here</tool_result>

Done reading.
"""

SESSION_CDATA = """\
<tool_use name="Write" id="w1"><param name="file_path">/x.py</param><param name="content"><![CDATA[print("hi")]]""" + """></param></tool_use>

<tool_result id="w1">OK</tool_result>
"""

SESSION_EDIT = """\
<tool_use name="Edit" id="e1"><param name="file_path">/f.py</param>\
<param name="old_string">x = 1</param><param name="new_string">x = 2</param></tool_use>

<tool_result id="e1">Edited</tool_result>
"""


def test_parse_simple_session():
    blocks = parse_session(SESSION_SIMPLE)
    assert len(blocks) == 4
    assert isinstance(blocks[0], AssistantText)
    assert blocks[0].content == "Hello world."
    assert isinstance(blocks[1], ToolCall)
    assert blocks[1].name == "Read"
    assert blocks[1].call_id == "r1"
    assert blocks[1].params == {"file_path": "/tmp/a.txt"}
    assert isinstance(blocks[2], ToolResult)
    assert blocks[2].call_id == "r1"
    assert blocks[2].content == "file content here"
    assert isinstance(blocks[3], AssistantText)
    assert "Done reading" in blocks[3].content


def test_parse_cdata_params():
    blocks = parse_session(SESSION_CDATA)
    assert len(blocks) == 2
    call = blocks[0]
    assert isinstance(call, ToolCall)
    assert call.name == "Write"
    assert call.params["content"] == 'print("hi")'


def test_render_edit_shows_diff():
    blocks = parse_session(SESSION_EDIT)
    output = render_html(blocks, finished=True)
    assert "monaco-diff-box" in output
    assert "diff-del" in output  # text fallback still present
    assert "diff-add" in output
    assert "x = 1" in output
    assert "x = 2" in output
    assert "<details" in output
    assert "bz-spin" not in output
    assert "monaco-editor" in output  # CDN script injected


def test_render_unfinished_has_spinner():
    blocks = parse_session("Working on it...")
    output = render_html(blocks, finished=False)
    assert "bz-spin" in output
    assert "Session en cours" in output
    output_finished = render_html(blocks, finished=True)
    assert "bz-spin" not in output_finished


# ── JSON parser tests ───────────────────────────────────────────────

def test_json_parse_user_assistant():
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "World"},
    ]
    blocks = parse_session_json(messages)
    assert len(blocks) == 2
    assert isinstance(blocks[0], UserMessage)
    assert blocks[0].content == "Hello"
    assert isinstance(blocks[1], AssistantText)
    assert blocks[1].content == "World"


def test_json_parse_tool_calls():
    messages = [
        {"role": "user", "content": "Read the file"},
        {
            "role": "assistant",
            "content": 'Let me read it.\n\n<tool_use name="Read" id="r1"><param name="file_path">/a.txt</param></tool_use>',
            "tool_calls": [{"id": "r1", "name": "Read", "input": {"file_path": "/a.txt"}}],
        },
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "file content"},
    ]
    blocks = parse_session_json(messages)
    assert isinstance(blocks[0], UserMessage)
    assert isinstance(blocks[1], AssistantText)
    assert "Let me read it" in blocks[1].content
    assert "tool_use" not in blocks[1].content
    assert isinstance(blocks[2], ToolCall)
    assert blocks[2].name == "Read"
    assert blocks[2].params == {"file_path": "/a.txt"}
    assert isinstance(blocks[3], ToolResult)
    assert blocks[3].call_id == "r1"
    assert blocks[3].content == "file content"
    assert blocks[3].tool_name == "Read"


def test_json_parse_multiple_tool_calls():
    messages = [
        {
            "role": "assistant",
            "content": '<tool_use name="Grep" id="g1"><param name="pattern">foo</param></tool_use>\n<tool_use name="Grep" id="g2"><param name="pattern">bar</param></tool_use>',
            "tool_calls": [
                {"id": "g1", "name": "Grep", "input": {"pattern": "foo", "path": "/src"}},
                {"id": "g2", "name": "Grep", "input": {"pattern": "bar", "path": "/src"}},
            ],
        },
        {"role": "tool", "tool_call_id": "g1", "name": "Grep", "content": "match1"},
        {"role": "tool", "tool_call_id": "g2", "name": "Grep", "content": "match2"},
    ]
    blocks = parse_session_json(messages)
    tool_calls = [b for b in blocks if isinstance(b, ToolCall)]
    results = [b for b in blocks if isinstance(b, ToolResult)]
    assert len(tool_calls) == 2
    assert len(results) == 2
    assert tool_calls[0].params["pattern"] == "foo"
    assert results[1].content == "match2"


def test_render_json_blocks_with_user_message():
    messages = [
        {"role": "user", "content": "Fix the bug"},
        {"role": "assistant", "content": "I'll fix it now."},
    ]
    blocks = parse_session_json(messages)
    output = render_html(blocks)
    assert "user-msg" in output
    assert "Fix the bug" in output
    assert "assistant" in output


def test_render_with_meta():
    blocks = [AssistantText(content="Hello")]
    output = render_html(blocks, meta={"session_id": "abc", "saved_at": "2026-01-01", "turn_count": 3})
    assert "session-meta" in output
    assert "abc" in output
    assert "3 turns" in output


def test_render_tool_summary_hints():
    blocks = [
        ToolCall(name="Read", call_id="r1", params={"file_path": "/src/main.py"}),
        ToolCall(name="Bash", call_id="b1", params={"command": "pytest -v"}),
        ToolCall(name="Grep", call_id="g1", params={"pattern": "TODO", "path": "/src"}),
    ]
    output = render_html(blocks)
    assert "main.py" in output
    assert "$ pytest -v" in output
    assert "&quot;TODO&quot;" in output


def test_json_parse_strips_tool_xml_from_content():
    messages = [
        {
            "role": "assistant",
            "content": 'Before\n\n<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>\n\nAfter',
            "tool_calls": [{"id": "b1", "name": "Bash", "input": {"command": "ls"}}],
        },
    ]
    blocks = parse_session_json(messages)
    text_blocks = [b for b in blocks if isinstance(b, AssistantText)]
    assert len(text_blocks) == 1
    assert "Before" in text_blocks[0].content
    assert "After" in text_blocks[0].content
    assert "<tool_use" not in text_blocks[0].content


def test_render_write_plan_block():
    blocks = [
        ToolCall(name="WritePlan", call_id="wp1", params={
            "content": "# My Plan\n\n- **file.py**: change X\n- **test.py**: add test"
        }),
        ToolResult(call_id="wp1", content="Plan saved"),
    ]
    output = render_html(blocks)
    assert "plan-block" in output
    assert "plan-header" in output
    assert "My Plan" in output
    assert "file.py" in output
    # WritePlan should NOT be rendered as a collapsed tool block
    assert 'class="tool-name">WritePlan' not in output


def test_json_parse_content_list():
    """User content can be a list of content blocks."""
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "First part"},
            {"type": "text", "text": "Second part"},
        ]},
    ]
    blocks = parse_session_json(messages)
    assert len(blocks) == 1
    assert isinstance(blocks[0], UserMessage)
    assert "First part" in blocks[0].content
    assert "Second part" in blocks[0].content


# ── Session completeness tests ──────────────────────────────────────

def test_json_parse_session_ending_with_assistant():
    """Session ending with final assistant text (no tool calls) is fully parsed."""
    messages = [
        {"role": "user", "content": "Fix the bug"},
        {
            "role": "assistant",
            "content": '<tool_use name="Edit" id="e1"><param name="file_path">/f.py</param>'
                       '<param name="old_string">x</param><param name="new_string">y</param></tool_use>',
            "tool_calls": [{"id": "e1", "name": "Edit",
                            "input": {"file_path": "/f.py", "old_string": "x", "new_string": "y"}}],
        },
        {"role": "tool", "tool_call_id": "e1", "name": "Edit", "content": "Edited"},
        {"role": "assistant", "content": "Done! The bug is fixed.", "tool_calls": []},
    ]
    blocks = parse_session_json(messages)
    assert isinstance(blocks[-1], AssistantText)
    assert "Done" in blocks[-1].content


def test_json_parse_session_ending_with_tool_results():
    """Session truncated after tool results (missing final assistant) still renders."""
    messages = [
        {"role": "user", "content": "Fix the bug"},
        {
            "role": "assistant",
            "content": "Let me fix it.",
            "tool_calls": [{"id": "e1", "name": "Edit",
                            "input": {"file_path": "/f.py", "old_string": "x", "new_string": "y"}},
                           {"id": "e2", "name": "Edit",
                            "input": {"file_path": "/g.py", "old_string": "a", "new_string": "b"}}],
        },
        {"role": "tool", "tool_call_id": "e1", "name": "Edit", "content": "Edited f.py"},
        {"role": "tool", "tool_call_id": "e2", "name": "Edit", "content": "Edited g.py"},
    ]
    blocks = parse_session_json(messages)
    assert isinstance(blocks[-1], ToolResult)
    assert blocks[-1].tool_name == "Edit"
    html_output = render_html(blocks, finished=True)
    assert "Edit" in html_output


def test_duplicate_ids_no_orphan_result():
    """Duplicate call_ids across turns must not produce orphan <pre> outside tool panels."""
    blocks = [
        ToolCall(name="Read", call_id="r1", params={"file_path": "/a.txt"}),
        ToolResult(call_id="r1", content="content A", tool_name="Read"),
        ToolCall(name="Read", call_id="r1", params={"file_path": "/b.txt"}),
        ToolResult(call_id="r1", content="content B", tool_name="Read"),
    ]
    output = render_html(blocks)
    # 2 actual result divs + 1 CSS rule = 3 occurrences of "result-section"
    assert output.count('class="result-section"') == 2
    # No orphan <pre> with tool result content outside tool panels
    assert ">content A</pre>" not in output.split("</details>")[-1]
    assert ">content B</pre>" not in output.split("</details>")[-1]
    # Each tool should show its own result
    assert "content A" in output
    assert "content B" in output


def test_json_parse_duplicate_tool_ids_across_turns():
    """Duplicate tool call IDs across turns should still pair correctly."""
    messages = [
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "g1", "name": "Grep",
                            "input": {"pattern": "foo", "path": "/src"}}],
        },
        {"role": "tool", "tool_call_id": "g1", "name": "Grep", "content": "match1"},
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "g1", "name": "Glob",
                            "input": {"pattern": "*.py"}}],
        },
        {"role": "tool", "tool_call_id": "g1", "name": "Glob", "content": "file.py"},
    ]
    blocks = parse_session_json(messages)
    tool_calls = [b for b in blocks if isinstance(b, ToolCall)]
    results = [b for b in blocks if isinstance(b, ToolResult)]
    assert len(tool_calls) == 2
    assert len(results) == 2
    assert tool_calls[0].name == "Grep"
    assert tool_calls[1].name == "Glob"
