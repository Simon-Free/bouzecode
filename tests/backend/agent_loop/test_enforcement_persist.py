# [desc] <tool_use name="FinalAnswer" id="f1"><param name="text">Test vérifiant que l'enforcement (Methodology manquant) est persisté comme message role="enforcement" avant l'assistant.</param></tool_use> [/desc]
"""Test that EnforcementWarning is persisted as a dedicated message.

When enforcement kicks in (missing Methodology / Snippet), loop.py yields an
EnforcementWarning (live, rendered by repl.py) AND now inserts a persistent
message with role="enforcement" into state.messages — placed BEFORE the current
assistant message so L443 (state.messages[-1]["tool_calls"] = ...) stays valid.

This file deliberately does NOT bypass enforcement (unlike test_partial_stream_recovery.py).

Le flux factice est SCRIPTÉ, un tour par appel, et se termine par une réponse sans
tool call — comme un vrai provider. Il rejouait auparavant éternellement le même tour
sans Methodology : la boucle ne pouvait pas en sortir et le fichier ne finissait jamais
(> 570 s de CPU, un worker immobilisé). Le script s'arrête donc net si la boucle
redemande un tour de plus que prévu, au lieu de tourner sans fin.
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


def _turn(text: str, tool_calls: list[dict]) -> AssistantTurn:
    return AssistantTurn(
        text=text, tool_calls=tool_calls,
        in_tokens=10, out_tokens=5, cache_read_tokens=0, cache_creation_tokens=0,
    )


def _scripted_stream(turns: list[AssistantTurn]):
    """Un provider est appelé UNE fois par tour et finit par répondre sans tool call.

    L'assertion est le garde-fou du montage : si la boucle réclame un tour hors script,
    le test échoue en une seconde en le disant, là où un flux rejoué à l'infini pendait.
    """
    served: list[AssistantTurn] = []

    def fake_stream(model, system, messages, tool_schemas, config):
        assert len(served) < len(turns), (
            f"la boucle a réclamé un tour n°{len(served) + 1} alors que le flux en "
            f"scripte {len(turns)} : elle n'a pas su s'arrêter"
        )
        turn = turns[len(served)]
        served.append(turn)
        yield StreamStarted()
        yield TextChunk(turn.text)
        yield turn

    return fake_stream, served


def _install(monkeypatch, fake_stream):
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)
    monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", lambda *a, **k: "ok")
    monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)
    # recovery best-effort: return None so no Methodology tool_call is injected
    monkeypatch.setattr("bouzecode.backend.agent.enforcement_call.recover_methodology", lambda *a, **k: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])


def test_enforcement_persisted_as_dedicated_message(monkeypatch):
    """Assistant batch without Methodology → a role="enforcement" message is
    inserted into state.messages, before the assistant, listing the missing tool.
    No synthetic role="user" message is created."""
    state = AgentState()
    config = _make_config()
    state.messages.append({"role": "user", "content": "do something"})
    state.user_loop_count = 1

    write_call = {"name": "Write", "input": {"file_path": "/tmp/x.txt", "content": "x"}, "id": "w1"}
    fake_stream, served = _scripted_stream([
        # No Methodology tool_call → triggers enforcement.
        _turn("Working.", [write_call]),
        # Plain text, no tool call → the model closes the session, as a real one does.
        _turn("Done.", []),
    ])
    _install(monkeypatch, fake_stream)

    list(run(None, state, config, "system prompt"))

    assert len(served) == 2, "les deux tours scriptés doivent avoir été joués"
    assert state.close_reason == "text_no_tools"

    enforcement_msgs = [m for m in state.messages if m.get("role") == "enforcement"]
    assert len(enforcement_msgs) == 1
    assert "Methodology" in enforcement_msgs[0]["missing_tools"]

    # inserted BEFORE the assistant batch it reports on (which keeps its tool_calls)
    idx = state.messages.index(enforcement_msgs[0])
    faulty_assistant = state.messages[idx + 1]
    assert faulty_assistant["role"] == "assistant"
    assert [tc["name"] for tc in faulty_assistant["tool_calls"]] == ["Write"]

    # never a synthetic user message beyond the initial one
    user_msgs = [m for m in state.messages if m.get("role") == "user"]
    assert len(user_msgs) == 1
