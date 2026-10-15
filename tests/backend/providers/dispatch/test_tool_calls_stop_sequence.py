# [desc] Verifie qu'aucun arret n'est delegue a l'API en mode XML et que les backends coupent le stream cote client sur la fermeture de batch [/desc]
"""Le verrou qui rend l'hallucination de resultats d'outils impossible.

Session 178666a6 : le modele a ecrit ses appels en markdown puis a **fabrique ses
propres resultats d'outils** dans la meme reponse. La parade avait ete de passer
`TOOL_CALLS_STOP` au provider comme stop sequence.

Cette parade avait un effet de bord fatal : une stop sequence coupe la generation
*ou que la sequence apparaisse*, y compris a l'interieur d'un `<param>` ou d'un
CDATA. Tout agent devant CITER la syntaxe du protocole (skill, doc, test, regex)
voyait donc son propre appel tronque, et le harness lui repondait « param never
closed ».

L'arret est desormais pris **cote client** : le parser expose `batch_closed`, qui
ne passe a True que sur une fermeture vue au niveau TOP (hors appel, hors param,
hors CDATA), et la boucle de stream raccroche des que ce flag est leve. Ces tests
verifient les deux moities du nouveau contrat, sans aucun appel reseau :
  1. plus aucun arret n'est transmis a l'API en mode XML ;
  2. chaque backend coupe bien son stream sur `batch_closed` — sans ce volet, on
     pourrait retirer le `break` sans casser un seul test et reperdre la garantie.

Le comportement fin du flag (fermeture reelle vs mention citee dans un param) est
prouve par tests/backend/xml_protocol/parser/test_batch_close_client_side.py.
"""
from __future__ import annotations


import pytest


class _Captured(Exception):
    """Interrompt l'appel des que la charge utile est capturee."""



# --- Anthropic --------------------------------------------------------------

def _anthropic_kwargs(monkeypatch, *, native_tools):
    """Renvoie les kwargs que stream_anthropic passe au SDK, sans reseau."""
    import bouzecode.backend.agent.providers.backends.anthropic_stream as mod

    seen: dict = {}

    def _fake_create(client, kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(mod, "build_anthropic_client", lambda *a, **k: object())
    monkeypatch.setattr(mod, "_create_anthropic_stream_with_retry", _fake_create)

    # `tests/conftest.py::_llm_network_guard` enveloppe stream_anthropic dans une
    # garde anti-appel-reel ; elle est posee avec functools.wraps precisement pour
    # rester introspectable, donc on deroule `__wrapped__` pour tester la vraie
    # fonction (le reseau reste inatteignable : le client et le stream sont fakes).
    fn = getattr(mod.stream_anthropic, "__wrapped__", mod.stream_anthropic)

    gen = fn(
        "fake-key",
        "claude-opus-4-8",
        "system prompt",
        [{"role": "user", "content": "Hello"}],
        [],
        {},
        native_tools=native_tools,
    )
    with pytest.raises(_Captured):
        next(gen)
    return seen


def test_anthropic_delegates_no_stop_to_the_api_in_xml_mode(monkeypatch):
    """Une stop sequence couperait aussi une citation legitime de la syntaxe."""
    kwargs = _anthropic_kwargs(monkeypatch, native_tools=None)
    assert "stop_sequences" not in kwargs


def test_anthropic_never_sends_a_stop_sequence_in_native_mode(monkeypatch):
    """En natif le modele n'ecrit pas de XML : rien a couper."""
    kwargs = _anthropic_kwargs(
        monkeypatch,
        native_tools=[{"name": "Read", "description": "d", "input_schema": {"type": "object"}}],
    )
    assert "stop_sequences" not in kwargs
    assert kwargs["tools"]


# Côté Anthropic, la garantie « le modèle ne peut pas écrire au-delà de son propre appel »
# est désormais prouvée par COMPORTEMENT (texte inventé après le lot ignoré, sortie comptée) :
# tests/backend/providers/test_comptage_tokens_e2e.py
# ::test_apres_le_lot_le_texte_invente_est_ignore_mais_la_sortie_est_comptee.
# Le flux ne raccroche plus sur `batch_closed` : il cesse de LIRE le texte et attend
# `message_delta`, seul porteur d'output_tokens (sinon 0 token de sortie par tour d'outils).


# --- OpenAI-compatible (OpenRouter / gateway preprod) -------------------------

class _FakeSession:
    def __init__(self, sink: dict):
        self._sink = sink

    def post(self, *args, **kwargs):
        self._sink.update(kwargs.get("json") or {})
        raise _Captured


def _openrouter_payload(monkeypatch, *, native):
    import bouzecode.backend.agent.providers.backends.openrouter_stream as mod

    seen: dict = {}
    monkeypatch.setattr(mod, "model_uses_native_tools", lambda model, config: native)

    gen = mod.stream_openrouter(
        api_key="fake-key",
        model="openai/gpt-x",
        system="system prompt",
        messages=[{"role": "user", "content": "Hello"}],
        tool_schemas=[],
        config={},
        session_factory=lambda: _FakeSession(seen),
    )
    with pytest.raises(_Captured):
        next(gen)
    return seen


def test_openrouter_delegates_no_stop_to_the_api_in_xml_mode(monkeypatch):
    payload = _openrouter_payload(monkeypatch, native=False)
    assert "stop" not in payload


def test_openrouter_never_sends_a_stop_in_native_mode(monkeypatch):
    payload = _openrouter_payload(monkeypatch, native=True)
    assert "stop" not in payload


# Closing on batch_closed is proven by behaviour (text after the batch is ignored, the
# trailing usage chunk still counted) in
# tests/backend/providers/backends/test_stream_usage_after_batch.py.
