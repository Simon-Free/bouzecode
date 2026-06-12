# [desc] Tests _inject_into_last_user_message helper for prepending text into user message content
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests _inject_into_last_user_message helper for prepending text into user message content</param></tool_use> [/desc]
"""Tests for _inject_into_last_user_message in dispatch.py."""
from bouzecode.backend.agent.providers.backends.dispatch import _inject_into_last_user_message


def test_inject_str_content():
    messages = [
        {"role": "user", "content": "Hello world"},
    ]
    _inject_into_last_user_message(messages, "INJECTED")
    assert messages[0]["content"] == "INJECTED\n\nHello world"


def test_inject_list_content():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Hello world"}]},
    ]
    _inject_into_last_user_message(messages, "INJECTED")
    assert messages[0]["content"] == [
        {"type": "text", "text": "INJECTED"},
        {"type": "text", "text": "Hello world"},
    ]


def test_inject_no_user_message():
    messages = [
        {"role": "assistant", "content": "Hi"},
    ]
    _inject_into_last_user_message(messages, "INJECTED")
    assert messages[0]["content"] == "Hi"


def test_inject_targets_last_user_message():
    messages = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Reply"},
        {"role": "user", "content": "Second"},
    ]
    _inject_into_last_user_message(messages, "INJECTED")
    assert messages[0]["content"] == "First"
    assert messages[2]["content"] == "INJECTED\n\nSecond"
