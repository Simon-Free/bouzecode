# [desc] Réflexions en double : une relance en vol du flux (réponse régénérée) et un thinking resté ouvert ne dupliquent plus la réflexion dans le message assistant enregistré. [/desc]
"""Deux sources de « réflexions en double » (sessions 3db4403a du 13/09, a3b38124 du 21/09) :

1. Le retry mid-stream de stream_anthropic relance la requête complète avec un parser neuf,
   mais les ThinkingChunk/TextChunk de la tentative avortée étaient déjà partis vers la
   boucle : ctx.thinking_parts accumulait les DEUX tentatives, et le message enregistré
   portait la réflexion deux fois.
2. Un tour coupé au milieu d'un <thinking> garde dans son texte brut un bloc NON fermé que
   _build_assistant_content ne retirait pas : la réflexion apparaissait une fois depuis
   thinking_parts, une fois depuis le texte brut.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.loop import run, _build_assistant_content
from bouzecode.backend.agent.providers import (
    StreamStarted, TextChunk, ThinkingChunk, AssistantTurn,
)
from bouzecode.backend.agent.providers.types import StreamRestart
from bouzecode.backend.agent.providers.backends import anthropic_stream as streamer
from bouzecode.backend.agent.providers.backends.anthropic_helpers import _StreamInterrupted
from tests.backend.providers.anthropic_sse_replay import sse, opening

# Le vrai streamer, lié au chargement (avant la garde anti-appel réel).
_real_stream_anthropic = streamer.stream_anthropic


@pytest.fixture(autouse=True)
def bypass_enforcement(monkeypatch):
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_test_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])


def _thinking_events(text):
    return [{"type": "content_block_start", "index": 0,
             "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "thinking_delta", "thinking": text}}]


def test_le_streamer_annonce_la_relance_avant_de_regenerer(monkeypatch):
    premiere = sse(*opening(), *_thinking_events("Je réfléchis."))
    seconde = sse(*opening(), *_thinking_events("Je réfléchis."),
                  {"type": "content_block_stop", "index": 0},
                  {"type": "content_block_start", "index": 1,
                   "content_block": {"type": "text", "text": ""}},
                  {"type": "content_block_delta", "index": 1,
                   "delta": {"type": "text_delta", "text": "Réponse."}},
                  {"type": "content_block_stop", "index": 1},
                  {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                                      "stop_sequence": None},
                   "usage": {"output_tokens": 5}})

    def coupe_puis_complet():
        yield from premiere
        raise _StreamInterrupted("coupure réseau")

    tentatives = [coupe_puis_complet(), iter(seconde)]

    class _Ctx:
        def __init__(self, it):
            self.it = it

        def __enter__(self):
            return self.it

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(streamer, "_create_anthropic_stream_with_retry",
                        lambda client, kwargs: _Ctx(tentatives.pop(0)))
    monkeypatch.setattr(streamer.time, "sleep", lambda s: None)
    evenements = list(_real_stream_anthropic(
        api_key="k", model="claude-opus-4-8", system=[{"type": "text", "text": "s"}],
        messages=[{"role": "user", "content": "go"}], tool_schemas=[], config={}))
    types = [type(e).__name__ for e in evenements
             if isinstance(e, (ThinkingChunk, TextChunk, StreamRestart))]
    assert types == ["ThinkingChunk", "StreamRestart", "ThinkingChunk", "TextChunk"]


def _patch_loop(monkeypatch, fake_stream):
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)


def test_la_boucle_oublie_la_tentative_avortee(monkeypatch):
    state = AgentState()
    state.messages.append({"role": "user", "content": "go"})
    state.user_loop_count = 1

    def fake_stream(model, system, messages, tool_schemas, config):
        yield StreamStarted()
        yield ThinkingChunk("Je réfléchis à la question.")
        yield TextChunk("Début de rép")
        yield StreamRestart()
        yield StreamStarted()
        yield ThinkingChunk("Je réfléchis à la question.")
        yield TextChunk("Réponse complète.")
        yield AssistantTurn("Réponse complète.", [], 100, 10)

    _patch_loop(monkeypatch, fake_stream)
    list(run(None, state, {"model": "test-model", "permission_mode": "accept-all"}, "sys"))
    assistant = next(m for m in state.messages if m["role"] == "assistant")
    assert assistant["content"].count("Je réfléchis à la question.") == 1
    assert "Début de rép" not in assistant["content"]


def test_thinking_non_ferme_dans_le_texte_brut_n_est_pas_repete():
    """Message 50 de a3b38124 : la réflexion, coupée avant sa fermeture, figurait deux fois."""
    brut = "<thinking>\n  Ce qui manque : savoir si l'usage est connu (cas probable : arrêt"
    contenu = _build_assistant_content(brut, ["\n  Ce qui manque : savoir si l'usage est connu "
                                              "(cas probable : arrêt"])
    assert contenu.count("Ce qui manque") == 1
