# [desc] Tests replay_messages output formatting for various message types including tools and XML stripping [/desc]
from bouzecode.ui.replay import replay_messages


def _run_replay(messages):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        replay_messages(messages)
    return buf.getvalue()


def test_empty_conversation():
    out = _run_replay([])
    assert "empty conversation" in out


def test_user_and_assistant_text():
    msgs = [
        {"role": "user", "content": "hello there"},
        {"role": "assistant", "content": "hi back", "tool_calls": []},
    ]
    out = _run_replay(msgs)
    assert "hello there" in out
    assert "hi back" in out
    assert "you" in out  # user header
    assert "bouz" in out  # assistant header


def test_assistant_tool_call_with_internal_format():
    msgs = [
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": "calling Bash",
            "tool_calls": [{"id": "tc1", "name": "Bash", "input": {"command": "ls"}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "name": "Bash", "content": "file1\nfile2"},
    ]
    out = _run_replay(msgs)
    assert "Bash(ls)" in out
    assert "lines" in out  # print_tool_end summary


def test_anthropic_native_blocks():
    msgs = [
        {"role": "user", "content": "do stuff"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "thinking aloud"},
                {"type": "tool_use", "id": "u1", "name": "Read", "input": {"file_path": "x.py"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "u1", "content": "abc"}],
        },
    ]
    out = _run_replay(msgs)
    assert "thinking aloud" in out
    assert "Read(x.py)" in out
    # the pure tool_result message must not show as a user turn
    assert out.count("you") == 1


def test_assistant_content_with_inline_tool_use_xml_is_stripped():
    msgs = [
        {"role": "user", "content": "read the file"},
        {
            "role": "assistant",
            "content": 'Let me read it.\n\n<tool_use name="Read" id="r10"><param name="file_path">/tmp/x.csv</param></tool_use>',
            "tool_calls": [{"id": "r10", "name": "Read", "input": {"file_path": "/tmp/x.csv"}}],
        },
        {"role": "tool", "tool_call_id": "r10", "name": "Read", "content": "file contents"},
    ]
    out = _run_replay(msgs)
    assert "Let me read it." in out
    assert "<tool_use" not in out
    assert "</tool_use>" not in out
    assert "Read(/tmp/x.csv)" in out


def test_pure_tool_result_user_message_is_skipped():
    msgs = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "u1", "content": "x"}],
        },
    ]
    out = _run_replay(msgs)
    # No user header for a message that only carries tool results
    assert "you" not in out
