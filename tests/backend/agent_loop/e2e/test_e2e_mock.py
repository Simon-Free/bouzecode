# [desc] E2E tests verifying MockLLM with raw XML tool_use responses through the bouzecode harness [/desc]
"""E2E tests using MockLLM with raw XML text responses."""
import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode

# A turn that CONTINUES must carry Methodology (enforcement); a turn that CLOSES
# must be plain text with NO tool call — a Methodology/Snippet-only batch is
# bookkeeping and earns a continue-nudge instead of closing (b83ade94).
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
    mock = MockLLM(["Hello! I am a mock."])
    result = bouzecode(["Hi there"], mock_llm=mock)
    assert "Hello! I am a mock." in result.last_reply
    assert mock.call_count == 1


def test_harness_mock_multi_turn():
    mock = MockLLM(["First reply", "Second reply"])
    result = bouzecode(["msg1", "msg2"], mock_llm=mock)
    assert mock.call_count == 2
    assert "Second reply" in result.last_reply
    assert len(result.turns) == 2


def test_harness_mock_tool_call_cycle():
    """Tool call (Bash) → mock execution → follow-up reply."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>',
        "The command returned ok.",
    ])
    result = bouzecode(["Run echo ok"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2
    assert "The command returned ok." in result.last_reply
    assert _has_tool_result(result.messages, "[Bash executed]")


def test_harness_mock_tools_dict():
    """Mock tool provides custom result for Read, with Snippet to satisfy enforcement."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Read" id="r1"><param name="file_path">/x.py</param></tool_use>',
        # Turn 2 is a meta-only batch (Methodology + Snippet): bookkeeping, so the
        # loop nudges instead of closing. Turn 3 closes on a plain, tool-free reply.
        f'{METH}\n<tool_use name="Snippet" id="s1"><param name="file_path">/x.py</param><param name="discard">true</param></tool_use>',
        "C'est fait.",
    ])
    result = bouzecode(
        ["Read x.py"],
        mock_llm=mock,
        mock_tools={"Read": "def hello(): pass\n"},
    )
    assert mock.call_count == 3
    assert _has_tool_result(result.messages, "def hello(): pass")


def test_harness_mock_tools_callable():
    """Mock tool callable generates dynamic result."""
    def custom_bash(tc):
        return f"output of: {tc['input']['command']}"

    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>',
        "Listed files.",
    ])
    result = bouzecode(
        ["List files"],
        mock_llm=mock,
        mock_tools={"Bash": custom_bash},
    )
    assert _has_tool_result(result.messages, "output of: ls")


def test_harness_mock_preserves_state():
    mock = MockLLM(["reply1", "reply2"])
    result = bouzecode(["hello", "world"], mock_llm=mock)
    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    asst_msgs = [m for m in result.messages if m.get("role") == "assistant"]
    assert len(user_msgs) >= 2
    assert len(asst_msgs) >= 2


def test_harness_mock_records_messages():
    mock = MockLLM(["hi", "bye"])
    bouzecode(["first", "second"], mock_llm=mock)
    first_msgs = mock.get_messages(0)
    user_in_first = [m for m in first_msgs if m.get("role") == "user"]
    assert len(user_in_first) >= 1


def test_harness_mock_malformed_xml_no_tools():
    """Text resembling XML but not valid tool_use should be treated as plain text."""
    mock = MockLLM(["Here is some <weird>xml</weird> stuff"])
    result = bouzecode(["test"], mock_llm=mock)
    assert mock.call_count == 1
    assert "<weird>xml</weird>" in result.last_reply
