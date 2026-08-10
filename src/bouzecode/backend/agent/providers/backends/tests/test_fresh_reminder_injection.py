"""Regression: the fresh-token reminders (_FRESH_REMINDER, audit note, working
memory) MUST be injected even when the last wire message is a tool_result.

Bug (session 76a7d766, T71): _append_to_last_user_message and
_inject_into_last_user_message only targeted role=="user" messages. In
dispatch.stream() these run BEFORE stream_anthropic() converts role="tool"
messages into user content-blocks, so when a turn's wire ends with
[{assistant, "."}, {tool, ...}] and contains NO role=="user" message, the loop
matched nothing and returned silently — dropping the reminder. The model then
received no "end your turn with a tool_use" hint, replied "." and looped on the
enforcement nudge. Fix: target role in ("user", "tool")."""

from bouzecode.backend.agent.providers.backends.dispatch import (
    _append_to_last_user_message,
    _inject_into_last_user_message,
    _FRESH_REMINDER,
)


def _tool_wire():
    # A wire ending on a tool_result with NO user message (T71 shape).
    return [
        {"role": "assistant", "content": "."},
        {"role": "tool", "tool_call_id": "b1", "content": "git log output"},
    ]


def test_append_injects_into_trailing_tool_message():
    wire = _tool_wire()
    _append_to_last_user_message(wire, _FRESH_REMINDER)
    last = wire[-1]
    assert last["role"] == "tool"
    # str content: reminder appended at the end
    assert _FRESH_REMINDER in last["content"]


def test_append_into_tool_message_with_list_content():
    wire = [
        {"role": "assistant", "content": "."},
        {"role": "tool", "content": [{"type": "text", "text": "git log output"}]},
    ]
    _append_to_last_user_message(wire, _FRESH_REMINDER)
    blocks = wire[-1]["content"]
    assert isinstance(blocks, list)
    assert blocks[-1] == {"type": "text", "text": _FRESH_REMINDER}


def test_inject_prepends_into_trailing_tool_message():
    wire = _tool_wire()
    _inject_into_last_user_message(wire, "[audit note]")
    assert "[audit note]" in wire[-1]["content"]


def test_user_message_still_preferred_and_unchanged_behavior():
    # Non-regression: when a real user message exists, it is still the target.
    wire = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": "ok"},
    ]
    _append_to_last_user_message(wire, _FRESH_REMINDER)
    assert _FRESH_REMINDER in wire[0]["content"]
    # the assistant message is untouched
    assert wire[1]["content"] == "ok"
