# [desc] Test vérifiant que l'enforcement (Methodology manquant) est persisté comme message role="enforcement" avant l'assistant. [/desc]
"""Test that EnforcementWarning is persisted as a dedicated message.

When enforcement kicks in (missing Methodology / Snippet), loop.py yields an
EnforcementWarning (live, rendered by repl.py) AND now inserts a persistent
message with role="enforcement" into state.messages — placed BEFORE the current
assistant message so L443 (state.messages[-1]["tool_calls"] = ...) stays valid.

This file deliberately does NOT bypass enforcement (unlike test_partial_stream_recovery.py).
"""
from __future__ import annotations

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.providers import TextChunk, AssistantTurn, StreamStarted


def _make_config():
    return {
        "model": "test-model",
        "permission_mode": "accept-all",
        "recover_memory": True,
    }


def _collect(gen):
    return list(gen)


def test_enforcement_persisted_as_dedicated_message(monkeypatch):
    """Assistant batch without Methodology → a role="enforcement" message is
    inserted into state.messages, before the assistant, listing the missing tool.
    No synthetic role="user" message is created."""
    state = AgentState()
    config = _make_config()
    state.messages.append({"role": "user", "content": "do something"})
    state.user_loop_count = 1

    # `loop.run` iterates `while True` until a turn comes back with no tool call.
    # A fake stream that always answers the same tool-calling turn therefore never
    # returns: it spun forever, one thread per turn, until thread creation itself
    # blocked. Turn 1 triggers the enforcement this test is about; turn 2 is a
    # plain text reply, which is how a conversation ends.
    turns: list[int] = []

    def fake_stream(model, system, messages, tool_schemas, config):
        turns.append(1)
        yield StreamStarted()
        if len(turns) > 1:
            yield TextChunk("Done.")
            yield AssistantTurn(text="Done.", tool_calls=[], in_tokens=1, out_tokens=1,
                                cache_read_tokens=0, cache_creation_tokens=0)
            return
        yield TextChunk("Working.")
        # No Methodology tool_call → triggers enforcement.
        yield AssistantTurn(
            text="Working.",
            tool_calls=[{"name": "Write", "input": {"file_path": "/tmp/x.txt", "content": "x"}, "id": "w1"}],
            in_tokens=10, out_tokens=5, cache_read_tokens=0, cache_creation_tokens=0,
        )

    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)
    monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", lambda *a, **k: "ok")
    monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)
    # recovery best-effort: return None so no Methodology tool_call is injected
    monkeypatch.setattr("bouzecode.backend.agent.enforcement_call.recover_methodology", lambda *a, **k: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])

    gen = run(None, state, config, "system prompt")
    _collect(gen)

    enforcement_msgs = [m for m in state.messages if m.get("role") == "enforcement"]
    assert len(enforcement_msgs) == 1
    assert "Methodology" in enforcement_msgs[0]["missing_tools"]

    # Inserted BEFORE the assistant message of its own turn — that ordering is
    # what keeps `state.messages[-1]["tool_calls"] = ...` pointing at the assistant.
    roles = [m.get("role") for m in state.messages]
    at = roles.index("enforcement")
    assert roles[at + 1] == "assistant"
    assert state.messages[at + 1]["content"] == "Working."

    # never a synthetic user message beyond the initial one
    user_msgs = [m for m in state.messages if m.get("role") == "user"]
    assert len(user_msgs) == 1
