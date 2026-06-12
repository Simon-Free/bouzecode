# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E tests for html_renderer: parses synthetic session JSON into blocks and validates rendered HTML output.</param></tool_use> [/desc]
"""E2E test for html_renderer: session.json messages → parse → render → validate HTML blocks."""
import json

from html_renderer.json_parser import parse_session_json
from html_renderer.renderer import render_html


# Synthetic session messages covering all block types
SESSION_MESSAGES = [
    {
        "role": "user",
        "content": "Show me the contents of config.py",
    },
    {
        "role": "assistant",
        "content": "I'll read that file for you.",
        "tool_calls": [
            {
                "id": "r1",
                "name": "Read",
                "input": {"file_path": "/project/config.py"},
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "r1",
        "name": "Read",
        "content": "# config\nDEBUG = True\n",
    },
    {
        "role": "assistant",
        "content": "Here's the config file. It sets DEBUG to True.",
        "tool_calls": [],
    },
    {
        "role": "user",
        "content": "Now write a test for it.",
    },
    {
        "role": "assistant",
        "content": "I'll create the test file.",
        "tool_calls": [
            {
                "id": "w1",
                "name": "Write",
                "input": {
                    "file_path": "/project/test_config.py",
                    "content": "def test_debug():\n    assert True\n",
                },
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "w1",
        "name": "Write",
        "content": "File written successfully.",
    },
]


def test_parse_session_json_produces_blocks():
    """parse_session_json must produce UserMessage, AssistantText, ToolCall, ToolResult blocks."""
    blocks = parse_session_json(SESSION_MESSAGES)
    # Expect: User, AssistantText, ToolCall(Read), ToolResult(r1),
    #         AssistantText, User, AssistantText, ToolCall(Write), ToolResult(w1)
    assert len(blocks) >= 7

    from html_renderer.parser import UserMessage, AssistantText, ToolCall, ToolResult

    user_blocks = [b for b in blocks if isinstance(b, UserMessage)]
    assistant_blocks = [b for b in blocks if isinstance(b, AssistantText)]
    tool_call_blocks = [b for b in blocks if isinstance(b, ToolCall)]
    tool_result_blocks = [b for b in blocks if isinstance(b, ToolResult)]

    assert len(user_blocks) == 2
    assert len(assistant_blocks) >= 2
    assert len(tool_call_blocks) == 2
    assert len(tool_result_blocks) == 2

    assert tool_call_blocks[0].name == "Read"
    assert tool_call_blocks[1].name == "Write"
    assert "config.py" in tool_call_blocks[0].params.get("file_path", "")


def test_render_html_contains_expected_markers():
    """Rendered HTML must contain user-msg, assistant, and tool-related CSS classes."""
    blocks = parse_session_json(SESSION_MESSAGES)
    html = render_html(blocks, finished=True, meta={
        "session_id": "test-001",
        "saved_at": "2025-01-01T00:00:00",
        "turn_count": 3,
        "first_message": "Show me the contents of config.py",
    })

    # Basic structure
    assert "<!DOCTYPE html>" in html
    assert "Bouzecode Session" in html

    # User message rendered
    assert "user-msg" in html
    assert "Show me the contents of config.py" in html

    # Assistant text rendered
    assert "assistant" in html
    assert "read that file" in html.lower() or "I&#x27;ll read" in html or "I'll read" in html

    # Tool call rendered (Read tool)
    assert "Read" in html
    assert "config.py" in html

    # Tool result content present
    assert "DEBUG = True" in html

    # Session meta rendered
    assert "test-001" in html
    assert "3 turns" in html


def test_render_html_session_with_list_content():
    """User messages with list-type content (multipart) are handled."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "First part."},
                {"type": "text", "text": "Second part."},
            ],
        },
        {
            "role": "assistant",
            "content": "Got both parts.",
            "tool_calls": [],
        },
    ]
    blocks = parse_session_json(messages)
    html = render_html(blocks, finished=True)

    assert "First part." in html
    assert "Second part." in html
    assert "Got both parts." in html


def test_render_html_unfinished_shows_spinner():
    """When finished=False, spinner HTML is included."""
    blocks = parse_session_json(SESSION_MESSAGES[:1])
    html = render_html(blocks, finished=False)
    # The renderer adds _SPINNER_HTML when not finished
    assert "spinner" in html.lower() or "loading" in html.lower() or "animation" in html.lower()
