"""Test that messages_to_anthropic handles tool_calls with missing 'inputs' key."""

from bouzecode.backend.agent.providers.conversion import messages_to_anthropic


def test_tool_call_without_inputs_key():
    """Tool calls with no parameters (no 'inputs' key) should not crash."""
    messages = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"name": "ListAgentTasks", "id": "x1"},
            ],
        },
    ]
    result = messages_to_anthropic(messages, cache_last=False)
    # 3 messages: user + assistant + synthetic tool_result (no matching "tool" message)
    assert len(result) == 3
    assert result[1]["role"] == "assistant"
    # The assistant content should contain the serialized tool_use XML
    assert 'name="ListAgentTasks"' in result[1]["content"]
    assert 'id="x1"' in result[1]["content"]


def test_tool_call_with_inputs_key():
    """Tool calls with 'inputs' key should serialize parameters correctly."""
    messages = [
        {"role": "user", "content": "do something"},
        {
            "role": "assistant",
            "content": "I will read the file.",
            "tool_calls": [
                {
                    "name": "Read",
                    "id": "r1",
                    "inputs": {"file_path": "/tmp/test.py"},
                },
            ],
        },
    ]
    result = messages_to_anthropic(messages, cache_last=False)
    assert len(result) == 3  # user + assistant + synthetic tool_result
    content = result[1]["content"]
    assert "I will read the file." in content
    assert 'name="Read"' in content
    assert 'id="r1"' in content
    assert "file_path" in content
    assert "/tmp/test.py" in content


def test_tool_call_with_input_singular_key():
    """Tool calls using 'input' (singular) should also work."""
    messages = [
        {"role": "user", "content": "test"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "name": "Bash",
                    "id": "b1",
                    "input": {"command": "echo hi"},
                },
            ],
        },
    ]
    result = messages_to_anthropic(messages, cache_last=False)
    content = result[1]["content"]
    assert 'name="Bash"' in content
    assert "command" in content
    assert "echo hi" in content
