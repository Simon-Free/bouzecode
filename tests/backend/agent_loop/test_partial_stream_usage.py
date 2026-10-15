# [desc] Test TDD vérifiant qu'un stream partiel (crash après UsageSnapshot) conserve les tokens réels au lieu de 0. [/desc]
"""When the stream dies mid-way, the tokens ALREADY billed by the provider must
not be reported as zero.

Anthropic sends `usage.input_tokens` / `cache_read_input_tokens` in
`message_start`, i.e. BEFORE any content. If the stream then crashes, the loop
used to rebuild a synthetic AssistantTurn with in/out/cache tokens hardcoded to
0, so a 48s turn was displayed (and accumulated) as free.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.state import AgentState, TurnDone
from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.providers import (
    StreamStarted,
    TextChunk,
    ToolCallParsed,
    UsageSnapshot,
)


@pytest.fixture(autouse=True)
def bypass_enforcement(monkeypatch):
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_test_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])


def _patch_loop(monkeypatch, fake_stream):
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)


def _state_with_user_msg():
    state = AgentState()
    state.messages.append({"role": "user", "content": "go"})
    state.user_loop_count = 1
    return state


class TestPartialStreamUsage:
    def test_crashed_stream_keeps_usage_seen_before_the_crash(self, monkeypatch):
        """Text-only partial stream: the usage snapshot received must be reported."""
        state = _state_with_user_msg()
        config = {"model": "test-model", "permission_mode": "accept-all"}

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            # Anthropic message_start: input usage known before any content.
            yield UsageSnapshot(
                in_tokens=1234, out_tokens=0,
                cache_read_tokens=7890, cache_creation_tokens=12,
            )
            yield TextChunk("partial answer")
            # Anthropic message_delta: output count refreshed as tokens stream.
            yield UsageSnapshot(
                in_tokens=1234, out_tokens=56,
                cache_read_tokens=7890, cache_creation_tokens=12,
            )
            raise ConnectionError("stream died")

        _patch_loop(monkeypatch, fake_stream)

        events = list(run(None, state, config, "system prompt"))

        turn_dones = [e for e in events if isinstance(e, TurnDone)]
        assert turn_dones, "a partial stream must still emit TurnDone"
        assert turn_dones[0].input_tokens == 1234
        assert turn_dones[0].output_tokens == 56

        assert state.total_input_tokens == 1234
        assert state.total_output_tokens == 56
        assert state.total_cache_read_tokens == 7890
        assert state.total_cache_creation_tokens == 12

    def test_crashed_stream_with_tools_keeps_usage(self, monkeypatch):
        """Same guarantee when tool calls were parsed before the crash."""
        state = _state_with_user_msg()
        config = {"model": "test-model", "permission_mode": "accept-all"}

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            yield UsageSnapshot(
                in_tokens=500, out_tokens=0,
                cache_read_tokens=0, cache_creation_tokens=300,
            )
            yield TextChunk("running a tool")
            yield ToolCallParsed("Bash", {"command": "echo hi"}, "b1")
            yield UsageSnapshot(
                in_tokens=500, out_tokens=42,
                cache_read_tokens=0, cache_creation_tokens=300,
            )
            raise ConnectionError("stream died")

        _patch_loop(monkeypatch, fake_stream)
        monkeypatch.setattr(
            "bouzecode.backend.agent.dag.execute_tool",
            lambda name, inputs, permission_mode=None, callback=None, config=None: "hi\n",
        )
        monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)

        events = list(run(None, state, config, "system prompt"))

        turn_dones = [e for e in events if isinstance(e, TurnDone)]
        assert turn_dones
        assert turn_dones[0].input_tokens == 500
        assert turn_dones[0].output_tokens == 42
        assert state.total_cache_creation_tokens == 300

    def test_crashed_stream_without_usage_is_estimated_and_flagged(self, monkeypatch):
        """No snapshot received (crash before any usage): the call was billed anyway.
        Serving 0 made whole sessions read "+0 in / +0 out" (21-25/09); the counts are
        now ESTIMATED from what was sent / received, and flagged as such."""
        state = _state_with_user_msg()
        config = {"model": "test-model", "permission_mode": "accept-all"}

        def fake_stream(model, system, messages, tool_schemas, config):
            yield StreamStarted()
            yield TextChunk("partial")
            raise ConnectionError("stream died")

        _patch_loop(monkeypatch, fake_stream)

        events = list(run(None, state, config, "system prompt"))

        turn_dones = [e for e in events if isinstance(e, TurnDone)]
        assert turn_dones
        assert turn_dones[0].input_tokens > 0 and turn_dones[0].input_estimated
        assert turn_dones[0].output_tokens > 0 and turn_dones[0].output_estimated
        assert state.total_input_tokens == turn_dones[0].input_tokens
        appel = [e for e in state.compaction_log if e.get("event") == "llm_call"][0]
        assert appel["api_input_estimated"] and appel["api_output_estimated"]
