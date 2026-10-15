# [desc] Entrée comptée d'un tour Anthropic : l'écriture de cache y figure une seule fois, quelle que soit la convention réelle de l'endpoint ; plus de « +-N fresh » négatif. [/desc]
"""Mesure du 2026-09-29 (debug_payloads, tours à froid du gateway, cache lu = 0) : 30 tours sur 32
ont `input_tokens` < `cache_creation_input_tokens` (ex. 907 contre 16 247). Le gateway EXCLUT donc
l'écriture de cache de l'entrée, alors que `anthropic_input_includes_cache_write` le range parmi
les passerelles qui l'incluent : l'entrée comptée perdait l'écriture, et le TUI affichait
« +-15K fresh » (entrée − écriture). Une entrée brute inférieure à l'écriture ne peut pas
l'inclure : c'est la réponse elle-même qui tranche."""
from __future__ import annotations

import pytest

from tests.backend.providers.anthropic_sse_replay import sse, text, closing, replay_stream, turn_of


def _flux(entree_brute: int, ecriture: int):
    ouverture = {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "content": [],
        "model": "claude-opus-5", "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": entree_brute, "output_tokens": 0,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": ecriture}}}
    return sse(ouverture, *text(0, "Bonjour."), *closing("end_turn"))


@pytest.mark.parametrize(("inclusion_annoncee", "entree_brute", "entree_attendue"), [
    ("1", 907, 907 + 16247),     # gateway réel : annoncé inclusif, entrée brute < écriture
    ("1", 17154, 17154),         # endpoint réellement inclusif : rien à ajouter
    ("0", 907, 907 + 16247),     # API officielle : exclusif, on ajoute
])
def test_l_ecriture_de_cache_est_comptee_une_seule_fois(monkeypatch, inclusion_annoncee,
                                                        entree_brute, entree_attendue):
    monkeypatch.setenv("BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE", inclusion_annoncee)
    tour = turn_of(replay_stream(monkeypatch, _flux(entree_brute, 16247), native_tools=False))
    assert tour.cache_creation_tokens == 16247
    assert tour.in_tokens == entree_attendue
    assert tour.in_tokens - tour.cache_creation_tokens >= 0   # « fresh » du TUI
