# [desc] L'appel Methodology du lot précédent et son tool_result ne sont plus redéclarés dans le fil : rejoué en argument d'outil, il faisait refuser claude-opus-5-5 (content_filter). [/desc]
"""Session bb991b7c (2026-10-07), claude-opus-5-5 sur la préprod du gateway : refus
`content_filter` aux tours 6, 8, 9, 10, 11. Rejeu ablatif : l'appel Methodology redéclaré
dans le message assistant déclenche le refus (8/8 avec, 0/8 sans) ; son texte est déjà dans
la note Methodology des blocs system.
"""
from __future__ import annotations

import json

from bouzecode.backend.agent.minimal_payload import build_minimal_payload
from bouzecode.backend.agent.snippet_wire import HARNESS_NOTE_KEY
from bouzecode.backend.agent.providers.backends.anthropic_native import messages_to_anthropic_native
from bouzecode.backend.agent.providers.backends.openrouter_native import messages_to_openai_native

NOTE = {"content": "T5 : config lue ; reste à vérifier les appels de grep."}
LECTURE = {"file_path": "src/app/config.py"}
RECHERCHE = {"pattern": "def charger", "path": "src"}
DEMANDE = {"role": "user", "content": "Corrige le chargement de la config."}

LOT_COMPLET = [
    DEMANDE,
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "tooluse_m", "name": "Methodology", "input": NOTE},
        {"id": "tooluse_r", "name": "Read", "input": LECTURE},
        {"id": "tooluse_g", "name": "Grep", "input": RECHERCHE},
    ]},
    {"role": "tool", "tool_call_id": "tooluse_m", "name": "Methodology",
     "content": "methodology append: now 30198 chars"},
    {"role": "tool", "tool_call_id": "tooluse_r", "name": "Read", "content": "1\tCONFIG = {}"},
    {"role": "tool", "tool_call_id": "tooluse_g", "name": "Grep", "content": "src/app/config.py:3"},
]

LOT_METHODOLOGY_SEUL = [
    DEMANDE,
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "tooluse_m", "name": "Methodology", "input": NOTE}]},
    {"role": "tool", "tool_call_id": "tooluse_m", "name": "Methodology",
     "content": "methodology append: now 30198 chars"},
]


def _ids_des_resultats(fil: list[dict]) -> list[str]:
    return [m["tool_call_id"] for m in fil if m.get("role") == "tool"]


def test_le_fil_minimal_ne_porte_plus_le_resultat_methodology():
    fil = build_minimal_payload(LOT_COMPLET)
    assert _ids_des_resultats(fil) == ["tooluse_r", "tooluse_g"]
    assert "methodology append" not in json.dumps(fil, ensure_ascii=False)


def test_l_avis_de_destruction_passe_au_premier_resultat_garde():
    """Hors du résultat depuis le 2026-10-07 : la consigne est posée à part (HARNESS_NOTE_KEY),
    pour le bloc <harness_notes> qui suit les tool_results."""
    fil = build_minimal_payload(LOT_COMPLET)
    premier = next(m for m in fil if m.get("role") == "tool")
    assert premier[HARNESS_NOTE_KEY].startswith("The tool_results above are destroyed")
    assert "[SYSTEM]" not in premier["content"]


def test_fil_openai_sans_appel_methodology_et_appels_apparies():
    fil = messages_to_openai_native(build_minimal_payload(LOT_COMPLET), "system")
    appels = [a for m in fil if m["role"] == "assistant" for a in m.get("tool_calls") or []]
    assert [(a["id"], a["function"]["name"], json.loads(a["function"]["arguments"]))
            for a in appels] == [("tooluse_r", "Read", LECTURE), ("tooluse_g", "Grep", RECHERCHE)]
    assert _ids_des_resultats(fil) == ["tooluse_r", "tooluse_g"]


def test_fil_anthropic_sans_appel_methodology_et_appels_apparies():
    fil = messages_to_anthropic_native(build_minimal_payload(LOT_COMPLET), cache_last=False)
    blocs = [b for m in fil if isinstance(m["content"], list) for b in m["content"]]
    appels = [(b["id"], b["name"]) for b in blocs if b.get("type") == "tool_use"]
    resultats = [b["tool_use_id"] for b in blocs if b.get("type") == "tool_result"]
    assert appels == [("tooluse_r", "Read"), ("tooluse_g", "Grep")]
    assert resultats == ["tooluse_r", "tooluse_g"]


def test_lot_methodology_seul_rend_un_fil_qui_finit_sur_la_demande():
    fil = build_minimal_payload(LOT_METHODOLOGY_SEUL)
    assert fil == [DEMANDE]
    for transport in (messages_to_openai_native(fil, "system"),
                      messages_to_anthropic_native(fil, cache_last=False)):
        assert transport[-1]["role"] == "user"
        assert "tooluse_m" not in json.dumps(transport)
