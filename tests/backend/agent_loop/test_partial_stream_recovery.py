# [desc] Tests that partial LLM stream crashes still execute already-parsed tool calls and checkpoint results. [/desc]
"""Tests for partial stream recovery in agent/loop.py.

When the LLM stream crashes after emitting some ToolCallParsed events,
the agent should build a synthetic AssistantTurn, execute the parsed tools,
checkpoint, and stop — instead of losing everything.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.state import AgentState, ToolStart, ToolEnd, TurnDone, CheckpointReady
from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.providers import TextChunk, ThinkingChunk, ToolCallParsed, AssistantTurn, StreamStarted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def bypass_enforcement(monkeypatch):
    """Disable enforcement hooks so tests don't get extra LLM cycles."""
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_test_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])

def _make_config():
    return {
        "model": "test-model",
        "permission_mode": "accept-all",
    }


def _make_state():
    return AgentState()


def _collect(gen):
    """Collect all events from a generator into a list."""
    return list(gen)


class FakeToolCallParsed:
    """Mimics what the XML parser yields mid-stream."""
    def __init__(self, name, inputs, tool_id):
        self.name = name
        self.inputs = inputs
        self.tool_id = tool_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPartialStreamRecovery:
    """Stream crashes after emitting ToolCallParsed events."""

    def test_crash_with_tools_executes_them(self, monkeypatch):
        """3 Write tool calls parsed, then stream crashes.
        All 3 should be executed and results saved in state."""
        state = _make_state()
        config = _make_config()
        state.messages.append({"role": "user", "content": "write 3 files"})
        state.user_loop_count = 1

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            yield TextChunk("I'll write 3 files.")
            yield ToolCallParsed("Write", {"file_path": "/tmp/a.txt", "content": "aaa"}, "w1")
            yield ToolCallParsed("Write", {"file_path": "/tmp/b.txt", "content": "bbb"}, "w2")
            yield ToolCallParsed("Write", {"file_path": "/tmp/c.txt", "content": "ccc"}, "w3")
            raise ConnectionError("stream died")

        def fake_execute_tool(name, inputs, permission_mode=None, callback=None, config=None):
            return f"wrote {inputs.get('file_path', '?')}"

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)
        monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", fake_execute_tool)
        monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)

        gen = run(None, state, config, "system prompt")
        events = _collect(gen)

        # Should have text chunks, tool parsed, tool start/end, turn done, checkpoint
        text_chunks = [e for e in events if isinstance(e, TextChunk)]
        tool_parsed = [e for e in events if isinstance(e, ToolCallParsed)]
        tool_starts = [e for e in events if isinstance(e, ToolStart)]
        tool_ends = [e for e in events if isinstance(e, ToolEnd)]
        checkpoints = [e for e in events if isinstance(e, CheckpointReady)]

        assert len(text_chunks) == 1
        assert text_chunks[0].text == "I'll write 3 files."
        assert len(tool_parsed) == 3
        assert len(tool_starts) == 3
        assert len(tool_ends) == 3
        assert len(checkpoints) >= 1

        # State should have assistant message + 3 tool results
        assistant_msgs = [m for m in state.messages if m["role"] == "assistant"]
        tool_msgs = [m for m in state.messages if m["role"] == "tool"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "I'll write 3 files."
        assert len(assistant_msgs[0]["tool_calls"]) == 3
        assert len(tool_msgs) == 3

    def test_crash_with_text_only_saves_it(self, monkeypatch):
        """Stream yields text then crashes (no tools).
        Text should be saved as assistant message, checkpoint emitted."""
        state = _make_state()
        config = _make_config()
        state.messages.append({"role": "user", "content": "hello"})
        state.user_loop_count = 1

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            yield TextChunk("Here is my ")
            yield TextChunk("response so far")
            raise ConnectionError("stream died")

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)

        gen = run(None, state, config, "system prompt")
        events = _collect(gen)

        text_chunks = [e for e in events if isinstance(e, TextChunk)]
        checkpoints = [e for e in events if isinstance(e, CheckpointReady)]

        assert len(text_chunks) == 2
        assert len(checkpoints) >= 1

        assistant_msgs = [m for m in state.messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "Here is my response so far"
        assert assistant_msgs[0]["tool_calls"] == []

    def test_crash_with_nothing_raises(self, monkeypatch):
        """Stream crashes immediately with no text or tools.
        Exception should propagate."""
        state = _make_state()
        config = _make_config()
        state.messages.append({"role": "user", "content": "hello"})
        state.user_loop_count = 1

        def fake_stream(model, system, messages, tool_schemas, config):
            raise ConnectionError("stream died immediately")

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)

        gen = run(None, state, config, "system prompt")
        with pytest.raises(ConnectionError, match="stream died immediately"):
            _collect(gen)

    def test_crash_preserves_text_and_tools(self, monkeypatch):
        """Stream yields text + 2 tools then crashes.
        Both text and tool results should be in state."""
        state = _make_state()
        config = _make_config()
        state.messages.append({"role": "user", "content": "do things"})
        state.user_loop_count = 1

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            yield TextChunk("Working on it...")
            yield ToolCallParsed("Read", {"file_path": "/tmp/x.py"}, "r1")
            yield ToolCallParsed("Grep", {"pattern": "def foo", "path": "/tmp"}, "g1")
            raise RuntimeError("network blip")

        def fake_execute_tool(name, inputs, permission_mode=None, callback=None, config=None):
            if name == "Read":
                return "file contents here"
            return "grep results here"

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)
        monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", fake_execute_tool)
        monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)

        gen = run(None, state, config, "system prompt")
        events = _collect(gen)

        tool_ends = [e for e in events if isinstance(e, ToolEnd)]
        assert len(tool_ends) == 2

        assistant_msgs = [m for m in state.messages if m["role"] == "assistant"]
        assert assistant_msgs[0]["content"] == "Working on it..."
        assert len(assistant_msgs[0]["tool_calls"]) == 2

        tool_msgs = [m for m in state.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_normal_stream_unaffected(self, monkeypatch):
        """Normal stream with AssistantTurn works exactly as before."""
        state = _make_state()
        config = _make_config()
        state.messages.append({"role": "user", "content": "hello"})
        state.user_loop_count = 1

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            yield TextChunk("Hello!")
            yield AssistantTurn(
                text="Hello!", tool_calls=[], in_tokens=100, out_tokens=20,
                cache_read_tokens=50, cache_creation_tokens=10,
            )

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)

        gen = run(None, state, config, "system prompt")
        events = _collect(gen)

        text_chunks = [e for e in events if isinstance(e, TextChunk)]
        turn_dones = [e for e in events if isinstance(e, TurnDone)]
        checkpoints = [e for e in events if isinstance(e, CheckpointReady)]

        assert len(text_chunks) == 1
        assert len(turn_dones) == 1
        assert turn_dones[0].input_tokens == 100
        assert turn_dones[0].output_tokens == 20
        assert len(checkpoints) >= 1

        assistant_msgs = [m for m in state.messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "Hello!"

    def test_partial_stream_does_not_loop_back_to_llm(self, monkeypatch):
        """After a partial recovery, the loop should NOT call the LLM again.
        It should break after executing tools + checkpointing."""
        state = _make_state()
        config = _make_config()
        state.messages.append({"role": "user", "content": "go"})
        state.user_loop_count = 1

        call_count = 0

        def fake_stream(model, system, messages, tool_schemas, config):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamStarted()
                yield TextChunk("doing stuff")
                yield ToolCallParsed("Bash", {"command": "echo hi"}, "b1")
                raise ConnectionError("oops")
            # Should never reach here
            yield StreamStarted()
            yield AssistantTurn(text="loop2", tool_calls=[], in_tokens=0, out_tokens=0)

        def fake_execute_tool(name, inputs, permission_mode=None, callback=None, config=None):
            return "hi\n"

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)
        monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", fake_execute_tool)
        monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)

        gen = run(None, state, config, "system prompt")
        events = _collect(gen)

        assert call_count == 1, "LLM should only be called once after partial recovery"
