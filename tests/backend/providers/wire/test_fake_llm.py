# [desc] Unit tests for MockLLM: text streaming, XML tool_use parsing, call counting, and exhaustion
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Unit tests for MockLLM: text streaming, XML tool_use parsing, call counting, and exhaustion</param></tool_use> [/desc]
"""Unit tests for the MockLLM class."""
import pytest
from tests.fake_llm import MockLLM
from bouzecode.backend.agent.providers.types import StreamStarted, TextChunk, ToolCallParsed, AssistantTurn


def test_mock_simple_text():
    mock = MockLLM(["Hello world!"])
    events = list(mock.stream("m", "", [], [], {}))
    assert isinstance(events[0], StreamStarted)
    assert isinstance(events[1], TextChunk)
    assert events[1].text == "Hello world!"
    assert isinstance(events[2], AssistantTurn)
    assert events[2].tool_calls == []


def test_mock_with_tool_call():
    response = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
    mock = MockLLM([response])
    events = list(mock.stream("m", "", [], [], {}))
    assert isinstance(events[0], StreamStarted)
    # Should have a ToolCallParsed event
    tc_events = [e for e in events if isinstance(e, ToolCallParsed)]
    assert len(tc_events) == 1
    assert tc_events[0].name == "Bash"
    assert tc_events[0].inputs == {"command": "echo hi"}
    assert tc_events[0].tool_id == "b1"
    # AssistantTurn should contain the tool call
    turn = events[-1]
    assert isinstance(turn, AssistantTurn)
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0]["name"] == "Bash"


def test_mock_text_and_tools():
    response = 'I will read the file.\n<tool_use name="Read" id="r1"><param name="file_path">/x.py</param></tool_use>'
    mock = MockLLM([response])
    events = list(mock.stream("m", "", [], [], {}))
    text_events = [e for e in events if isinstance(e, TextChunk)]
    tc_events = [e for e in events if isinstance(e, ToolCallParsed)]
    assert len(text_events) >= 1
    assert "I will read the file." in "".join(e.text for e in text_events)
    assert len(tc_events) == 1
    assert tc_events[0].name == "Read"


def test_mock_multiple_tools():
    response = (
        '<tool_use name="Methodology" id="m1"><param name="content">plan</param></tool_use>'
        '<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>'
    )
    mock = MockLLM([response])
    events = list(mock.stream("m", "", [], [], {}))
    tc_events = [e for e in events if isinstance(e, ToolCallParsed)]
    assert len(tc_events) == 2
    assert tc_events[0].name == "Methodology"
    assert tc_events[1].name == "Bash"


def test_mock_call_count():
    mock = MockLLM(["a", "b", "c"])
    assert mock.call_count == 0
    list(mock.stream("m", "", [], [], {}))
    assert mock.call_count == 1
    list(mock.stream("m", "", [], [], {}))
    assert mock.call_count == 2


def test_mock_exhausted():
    mock = MockLLM(["only one"])
    list(mock.stream("m", "", [], [], {}))
    with pytest.raises(AssertionError, match="only 1 responses configured"):
        list(mock.stream("m", "", [], [], {}))


def test_mock_records_messages():
    mock = MockLLM(["reply"])
    msgs = [{"role": "user", "content": "hello"}]
    list(mock.stream("model-x", "sys", msgs, [{"name": "Bash"}], {"key": "val"}))
    recorded = mock.recorded_calls[0]
    assert recorded["model"] == "model-x"
    assert recorded["messages"] == msgs
    assert recorded["tool_schemas"] == [{"name": "Bash"}]
