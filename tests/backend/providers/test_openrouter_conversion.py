# [desc] Tests OpenRouter backend helpers that flatten system blocks and messages to OpenAI format.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests OpenRouter backend helpers that flatten system blocks and messages to OpenAI format.</param></tool_use> [/desc]
"""Tests for _system_text, _content_to_text and _messages_to_openai."""
from bouzecode.backend.agent.providers.backends.openrouter_stream import (
    _system_text, _content_to_text, _messages_to_openai,
)


def test_system_text_from_blocks_joins_text():
    blocks = [
        {"type": "text", "text": "STABLE"},
        {"type": "text", "text": "TOOLS"},
        {"type": "text", "text": ""},
    ]
    assert _system_text(blocks) == "STABLE\n\nTOOLS"


def test_system_text_passthrough_for_string():
    assert _system_text("PLAIN") == "PLAIN"


def test_content_to_text_flattens_block_list():
    content = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    assert _content_to_text(content) == "a\nb"


def test_content_to_text_passthrough_for_string():
    assert _content_to_text("hello") == "hello"


def test_messages_to_openai_prepends_system_and_keeps_strings():
    messages = [{"role": "user", "content": "Hi"}]
    oai = _messages_to_openai(messages, "SYS")
    assert oai[0] == {"role": "system", "content": "SYS"}
    assert oai[1]["role"] == "user"
    assert oai[1]["content"] == "Hi"
    assert all(isinstance(m["content"], str) for m in oai)


def test_messages_to_openai_serializes_tool_calls_as_xml():
    messages = [
        {"role": "user", "content": "run"},
        {"role": "assistant", "content": "ok",
         "tool_calls": [{"name": "read_file", "id": "t1", "inputs": {"path": "x"}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "data"},
    ]
    oai = _messages_to_openai(messages, "SYS")
    assistant = next(m for m in oai if m["role"] == "assistant")
    assert "read_file" in assistant["content"]
    assert all(isinstance(m["content"], str) for m in oai)
