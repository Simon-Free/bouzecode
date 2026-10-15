"""Refus masqué du gateway : UNE relance, system aplati en une chaîne.

Incident 2026-09-29 11:21 (agent 4444476c3d1d, ticket 09bdd2b9) : refus du classifieur rendu
en `end_turn` vide par LiteLLM, alors que le thinking manuel était déjà retiré. Rejoué avec
un nonce varié, le même payload refuse 12 fois sur 96 avec le system en 5 blocs, 0 sur 48
avec le system en une chaîne. Le refus n'est donc ni déterministe ni sans remède.
"""
import inspect
import json

import pytest

from bouzecode.backend.agent.providers.thinking_level import system_for_refusal_retry
from bouzecode.backend.agent.providers.types import AssistantTurn
from tests.backend.providers.test_anthropic_empty_completion import FakeStreamCtx, _events

MODULE = "bouzecode.backend.agent.providers.backends.anthropic_stream"
SYSTEM_BLOCKS = [
    {"type": "text", "text": "prefixe stable", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "note de methodologie", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "contexte de session"},
]


class RecordingStreams:
    """Sert les flux dans l'ordre et garde le `system` de chaque requête émise."""

    def __init__(self, streams):
        self._streams = list(streams)
        self.systems_sent = []

    def __call__(self, client, kwargs):
        self.systems_sent.append(kwargs["system"])
        return FakeStreamCtx(self._streams.pop(0))


@pytest.fixture
def serve(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends.completion_diagnostics.DIAGNOSTICS_DIR",
        tmp_path / "diagnostics")

    def _serve(streams):
        recorder = RecordingStreams(streams)
        monkeypatch.setattr(f"{MODULE}.build_anthropic_client", lambda api_key, base_url=None: object())
        monkeypatch.setattr(f"{MODULE}._create_anthropic_stream_with_retry", recorder)
        return recorder

    return _serve


def _final_turn(system) -> AssistantTurn:
    from bouzecode.backend.agent.providers.backends import anthropic_stream
    stream_anthropic = inspect.unwrap(anthropic_stream.stream_anthropic)
    events = list(stream_anthropic(
        api_key="sk-ant-fake", model="claude-opus-5", system=system,
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[], config={}))
    return next(e for e in events if isinstance(e, AssistantTurn))


def test_masked_refusal_is_retried_once_with_a_flat_system(serve):
    recorder = serve([_events("", out_tokens=3), _events("Hello")])
    turn = _final_turn(SYSTEM_BLOCKS)
    assert turn.text == "Hello" and not turn.refusal
    assert recorder.systems_sent[0] == SYSTEM_BLOCKS
    assert recorder.systems_sent[1] == "prefixe stable\n\nnote de methodologie\n\ncontexte de session"


def test_refused_attempt_tokens_are_counted_in_the_turn(serve):
    serve([_events("", out_tokens=3), _events("Hello", out_tokens=40)])
    assert _final_turn(SYSTEM_BLOCKS).out_tokens == 43


def test_second_masked_refusal_stops_and_is_reported(serve, tmp_path):
    recorder = serve([_events("", out_tokens=3)] * 3)
    turn = _final_turn(SYSTEM_BLOCKS)
    assert len(recorder.systems_sent) == 2, "une seule relance, jamais plus"
    assert turn.refusal and "LiteLLM" in turn.refusal
    dumps = sorted((tmp_path / "diagnostics").glob("*.json"))
    assert [json.loads(d.read_text("utf-8"))["reason"] for d in dumps] == ["masked_refusal"] * 2


def test_system_already_flat_has_no_retry_variant():
    assert system_for_refusal_retry("deja une chaine") is None
    assert system_for_refusal_retry([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\n\nb"
