# [desc] gateway_preprod / gateway_openai (chat/completions): a content_filter refusal is surfaced in one call, never retried as-is, with a diagnostic. [/desc]
"""Le 2026-10-05, la route `/chat/completions` relançait un refus `content_filter` une fois,
system aplati. Ablation sur payload réel (session 28738fd0, 2026-10-12) : le refus est
déterministe pour un contexte donné, la relance payait un appel pour le même refus. Il remonte
tel quel ; la boucle rejoue le tour avec la note compactée (test_note_compactee_sur_refus)."""
import copy
import json

import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn

SYSTEM_BLOCKS = [
    {"type": "text", "text": "prefixe stable", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "note de methodologie", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "contexte de session"},
]
CONTENT_FILTER_SSE = (
    'data: {"choices":[{"delta":{"content":"","role":"assistant"},'
    '"finish_reason":"content_filter"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":2}}'
)
GOOD_SSE = (
    'data: {"choices":[{"delta":{"content":"Bonjour"},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":10}}'
)


class FakeResponse:
    ok = True
    status_code = 200
    encoding = "utf-8"
    text = ""

    def __init__(self, sse_line):
        self._sse_line = sse_line

    def iter_lines(self, decode_unicode=False):
        yield self._sse_line
        yield "data: [DONE]"


class RecordingGateway:
    """Faux gateway : sert les réponses dans l'ordre et garde une copie de chaque payload."""

    def __init__(self, sse_lines):
        self._sse_lines = list(sse_lines)
        self.payloads = []

    def post(self, url, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs["json"]))
        return FakeResponse(self._sse_lines.pop(0))


@pytest.fixture
def diagnostics_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends.completion_diagnostics.DIAGNOSTICS_DIR",
        tmp_path / "diagnostics")
    return tmp_path / "diagnostics"


def _final_turn(gateway: RecordingGateway, provider_label: str) -> AssistantTurn:
    from bouzecode.backend.agent.providers.backends.openrouter_stream import stream_openrouter
    events = list(stream_openrouter(
        api_key="k-fake", model="claude-opus-5-5", system=SYSTEM_BLOCKS,
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[], config={},
        base_url="https://gateway.example/v1", session_factory=lambda: gateway,
        send_reasoning=False, provider_label=provider_label,
    ))
    return next(e for e in events if isinstance(e, AssistantTurn))


@pytest.mark.parametrize("provider_label", ["gateway preprod", "gateway prod"])
def test_un_refus_content_filter_remonte_en_un_seul_appel(diagnostics_dir, provider_label):
    """Le gateway refuse : un seul POST, le tour remonte refusé, sans tentative écartée."""
    gateway = RecordingGateway([CONTENT_FILTER_SSE, GOOD_SSE])
    turn = _final_turn(gateway, provider_label)
    assert len(gateway.payloads) == 1, "aucune relance à l'identique"
    assert turn.refusal and turn.stop_reason == "content_filter"
    assert turn.tentatives_ecartees == []
    assert turn.out_tokens == 2, "les tokens de l'appel refusé restent comptés"


def test_le_refus_laisse_un_diagnostic(diagnostics_dir):
    _final_turn(RecordingGateway([CONTENT_FILTER_SSE]), "gateway preprod")
    dumps = sorted(diagnostics_dir.glob("*.json"))
    assert [json.loads(d.read_text("utf-8"))["reason"] for d in dumps] == [
        "content_filter_refusal"]
