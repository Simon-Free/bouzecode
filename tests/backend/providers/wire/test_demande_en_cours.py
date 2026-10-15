# [desc] La demande utilisateur en cours ouvre le fil de chaque tour d'agent, sur les deux transports. [/desc]
"""Le premier message envoyé au modèle pour un tour d'agent est la demande utilisateur.

Sans lui, le gateway préprod refusait claude-opus-5-5 en `content_filter` (12/12 sur la
session 0a3ed5c5, tour 13 ; 0/12 avec la demande en tête).
"""
from __future__ import annotations

import json

from bouzecode.backend.agent.demande_en_cours import (
    DEMANDE_UTILISATEUR,
    LONGUEUR_MAX_DEMANDE,
    PREFIXE,
)
from bouzecode.backend.agent.minimal_payload import build_messages_for_api
from bouzecode.backend.agent.providers.backends.anthropic_native import (
    messages_to_anthropic_native,
)
from bouzecode.backend.agent.providers.backends.openrouter_native import (
    messages_to_openai_native,
)
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, ContextState

DEMANDE = "Corrige le bug du tour 13 et ajoute un test."


class _Etat:
    def __init__(self, messages, note=""):
        self.messages = messages
        self.context_state = ContextState()
        if note:
            self.context_state.notes[METHODOLOGY_NOTE] = note


def _tour_13():
    """Historique d'un tour >= 2 : le message tapé est loin derrière, le lot vivant en queue."""
    return [
        {"role": "user", "content": DEMANDE, DEMANDE_UTILISATEUR: True},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": "x"},
        {"role": "user", "content": "(System Automated Event): relance du harnais"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "m1", "name": "Methodology", "input": {"note": "n"}},
            {"id": "b1", "name": "BashOutput", "input": {"bash_id": "1"}}]},
        {"role": "tool", "tool_call_id": "m1", "name": "Methodology", "content": "ok"},
        {"role": "tool", "tool_call_id": "b1", "name": "BashOutput", "content": "sortie"},
    ]


def test_tour_suivant_commence_par_la_demande():
    fil = build_messages_for_api(_Etat(_tour_13()), {})

    assert fil[0] == {"role": "user", "content": PREFIXE + DEMANDE}
    assert fil[0]["content"].startswith("[MESSAGE USER EN COURS]: ")
    # Le résultat Methodology du lot ne passe plus sur le fil (test_methodology_hors_fil).
    assert [m["role"] for m in fil] == ["user", "assistant", "tool"]


def test_dernier_message_tape_l_emporte():
    messages = [{"role": "user", "content": "ancienne demande", DEMANDE_UTILISATEUR: True},
                {"role": "assistant", "content": "fait"}] + _tour_13()
    fil = build_messages_for_api(_Etat(messages), {})

    assert fil[0]["content"] == PREFIXE + DEMANDE
    assert sum(1 for m in fil if "ancienne demande" in str(m.get("content"))) == 0


def test_tour_1_pas_de_doublon():
    fil = build_messages_for_api(
        _Etat([{"role": "user", "content": DEMANDE, DEMANDE_UTILISATEUR: True}]), {})

    assert len(fil) == 1
    assert fil[0]["role"] == "user" and fil[0]["content"] == DEMANDE


def test_demande_longue_tronquee_a_100_caracteres():
    longue = "Refonds le module de facturation. " * 10
    messages = [dict(m) for m in _tour_13()]
    messages[0]["content"] = longue
    fil = build_messages_for_api(_Etat(messages), {})

    assert LONGUEUR_MAX_DEMANDE == 100
    assert fil[0]["content"] == PREFIXE + longue.strip()[:100] + "…"


def test_demande_de_100_caracteres_inchangee():
    pile = "x" * LONGUEUR_MAX_DEMANDE
    messages = [dict(m) for m in _tour_13()]
    messages[0]["content"] = f"  {pile}  "
    fil = build_messages_for_api(_Etat(messages), {})

    assert fil[0]["content"] == PREFIXE + pile


def test_tour_1_demande_longue_pas_de_doublon():
    longue = "Refonds le module de facturation. " * 10
    fil = build_messages_for_api(
        _Etat([{"role": "user", "content": longue, DEMANDE_UTILISATEUR: True}]), {})

    assert len(fil) == 1
    assert fil[0]["content"] == longue


def test_session_non_marquee_repli_sur_la_note():
    """Session antérieure au marquage : la demande vient du dernier bloc `## User` de la note."""
    messages = [dict(m) for m in _tour_13()]
    messages[0].pop(DEMANDE_UTILISATEUR)
    note = f"## User @2026-10-05 10:00:00\nvieille\n\n## Plan\np\n\n## User @2026-10-05 11:00:00\n{DEMANDE}\n"
    fil = build_messages_for_api(_Etat(messages, note), {})

    assert fil[0] == {"role": "user", "content": PREFIXE + DEMANDE}


def test_les_deux_transports_gardent_la_demande_en_tete():
    fil = build_messages_for_api(_Etat(_tour_13()), {})

    anthropic = messages_to_anthropic_native(fil, cache_last=False)
    assert anthropic[0] == {"role": "user", "content": PREFIXE + DEMANDE}
    assert anthropic[1]["role"] == "assistant"
    assert {b["id"] for b in anthropic[1]["content"] if b["type"] == "tool_use"} == {"b1"}
    assert [b["type"] for b in anthropic[2]["content"]] == ["tool_result"]

    openai = messages_to_openai_native(fil, "system")
    assert openai[1] == {"role": "user", "content": PREFIXE + DEMANDE}
    assert openai[2]["role"] == "assistant"
    assert {tc["id"] for tc in openai[2]["tool_calls"]} == {"b1"}
    assert [m["role"] for m in openai[3:]] == ["tool"]


def test_appel_annexe_non_modifie(monkeypatch):
    """Un appel annexe (compaction, juge…) passe par `stream` sans tool_schemas : ses messages
    partent tels quels, sans demande ajoutée — même avec une demande dans la note."""
    from bouzecode.backend.agent.providers import SystemPayload
    from bouzecode.backend.agent.providers.backends.dispatch import stream

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    contexte = ContextState()
    contexte.notes[METHODOLOGY_NOTE] = f"## User @2026-10-05 11:00:00\n{DEMANDE}\n"
    messages = [{"role": "user", "content": "Résume ceci."}]
    config = {"model": "claude-sonnet-4", "_context_state": contexte}

    premier = next(stream("claude-sonnet-4", "juge", messages, [], config))

    assert isinstance(premier, SystemPayload)
    # Seule la note (en <working_notes>, 2026-10-07) précède le message : aucune demande ajoutée.
    assert len(premier.messages) == 1 and PREFIXE not in json.dumps(premier.messages)
    assert premier.messages[0]["content"][-1]["text"].endswith("</working_notes>\n\nRésume ceci.")
