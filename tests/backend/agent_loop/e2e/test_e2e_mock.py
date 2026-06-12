# [desc] E2E tests validating MockLLM harness: simple replies, multi-turn, tool call cycles, and state tracking. [/desc]
"""E2E tests using MockLLM with raw XML text responses."""
import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode

# Every mock response must include Methodology to avoid enforcement hook retries
METH = '<tool_use name="Methodology" id="m1"><param name="content">test</param></tool_use>'


def _has_tool_result(messages, content_substr):
    """Check if any message contains a tool_result with content_substr."""
    for m in messages:
        if m.get("role") == "tool":
            if content_substr in str(m.get("content", "")):
                return True
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        for sub in result_content:
                            if content_substr in str(sub.get("text", "")):
                                return True
                    elif content_substr in str(result_content):
                        return True
    return False


def test_harness_mock_simple_reply():
    mock = MockLLM([f"Hello! I am a mock.\n{METH}"])
    result = bouzecode(["Hi there"], mock_llm=mock)
    assert "Hello! I am a mock." in result.last_reply
    assert mock.call_count == 1


def test_harness_mock_multi_turn():
    mock = MockLLM([f"First reply\n{METH}", f"Second reply\n{METH}"])
    result = bouzecode(["msg1", "msg2"], mock_llm=mock)
    assert mock.call_count == 2
    assert "Second reply" in result.last_reply
    assert len(result.turns) == 2


def test_harness_mock_tool_call_cycle():
    """Tool call (Bash) → mock execution → follow-up reply."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>',
        f"The command returned ok.\n{METH}",
    ])
    result = bouzecode(["Run echo ok"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2
    assert "The command returned ok." in result.last_reply
    assert _has_tool_result(result.messages, "[Bash executed]")


def test_harness_mock_tools_dict():
    """Mock tool provides custom result for Read, with Snippet to satisfy enforcement."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Read" id="r1"><param name="file_path">/x.py</param></tool_use>',
        # Turn 2 is a meta-only batch (Methodology + Snippet) → the loop ends the
        # turn (nothing actionable to send back), so only 2 calls happen.
        f'done.\n{METH}\n<tool_use name="Snippet" id="s1"><param name="file_path">/x.py</param><param name="discard">true</param></tool_use>',
    ])
    result = bouzecode(
        ["Read x.py"],
        mock_llm=mock,
        mock_tools={"Read": "def hello(): pass\n"},
    )
    assert mock.call_count == 2
    assert _has_tool_result(result.messages, "def hello(): pass")


def test_harness_mock_tools_callable():
    """Mock tool callable generates dynamic result."""
    def custom_bash(tc):
        return f"output of: {tc['input']['command']}"

    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>',
        f"Listed files.\n{METH}",
    ])
    result = bouzecode(
        ["List files"],
        mock_llm=mock,
        mock_tools={"Bash": custom_bash},
    )
    assert _has_tool_result(result.messages, "output of: ls")


def test_harness_mock_preserves_state():
    mock = MockLLM([f"reply1\n{METH}", f"reply2\n{METH}"])
    result = bouzecode(["hello", "world"], mock_llm=mock)
    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    asst_msgs = [m for m in result.messages if m.get("role") == "assistant"]
    assert len(user_msgs) >= 2
    assert len(asst_msgs) >= 2


def test_harness_mock_records_messages():
    mock = MockLLM([f"hi\n{METH}", f"bye\n{METH}"])
    bouzecode(["first", "second"], mock_llm=mock)
    first_msgs = mock.get_messages(0)
    user_in_first = [m for m in first_msgs if m.get("role") == "user"]
    assert len(user_in_first) >= 1


def test_harness_mock_malformed_xml_no_tools():
    """Text resembling XML but not valid tool_use should be treated as plain text."""
    mock = MockLLM([f"Here is some <weird>xml</weird> stuff\n{METH}"])
    result = bouzecode(["test"], mock_llm=mock)
    assert mock.call_count == 1
    assert "<weird>xml</weird>" in result.last_reply
