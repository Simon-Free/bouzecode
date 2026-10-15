# [desc] Les compteurs de tokens d'une session (totaux + journal par appel, source de /turns et /costs) sont ceux que l'API a annoncés, pipeline réel contre un faux serveur Anthropic. [/desc]
"""Ce que l'utilisateur lit dans « Coûts & tours » vient des totaux de session et des entrées
`llm_call` / `side_call` du compaction_log. On fait tourner le VRAI pipeline (client, SSE,
parser XML, boucle) contre `tests/mock_anthropic_server.py`, dont l'usage est connu :
input 100 par appel, output = somme des longueurs des fragments // 4."""
from __future__ import annotations

import sys

import pytest

from tests.e2e_harness import bouzecode

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mock_api e2e hangs on Windows (threaded werkzeug + httpx streaming)",
)

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _sortie_annoncee(texte: str) -> int:
    return len(texte) // 4  # règle de tests/mock_anthropic_server.py::_render_sse


def _appels(result, event="llm_call"):
    return [e for e in result.state.compaction_log if e.get("event") == event]


def test_un_tour_d_outils_compte_la_sortie_annoncee_par_l_api():
    """Tour d'outils en XML : le client cesse de LIRE le texte à la fermeture du lot, mais
    doit encore recevoir `message_delta`, seul porteur de output_tokens. Avant correctif :
    0 token de sortie sur chaque tour d'outils (mesuré au bac à sable : 0 servi, 102 réels)."""
    tour_outils = f"Je note.\n<tool_calls>\n{METH}\n</tool_calls>"
    tour_final = "Voilà, c'est fait."
    result = bouzecode(["note ça"], mock_api=[tour_outils, tour_final])

    appels = _appels(result)
    assert [a["api_output_tokens"] for a in appels][:2] == [
        _sortie_annoncee(tour_outils), _sortie_annoncee(tour_final)]
    assert not any(a.get("api_output_estimated") for a in appels[:2])
    assert result.state.total_output_tokens == sum(a["api_output_tokens"] for a in appels)


def test_une_sortie_jamais_annoncee_est_estimee_et_signalee():
    """Flux coupé avant `message_delta` : la sortie a été générée et facturée. La session
    ne doit pas afficher 0, mais une estimation EXPLICITEMENT marquée comme telle."""
    texte = "Réponse partielle " * 40
    result = bouzecode(["vas-y"], mock_api=[{"chunks": [texte], "truncate_after": 1}, "fin."])

    premier = _appels(result)[0]
    assert premier["api_output_tokens"] > 0
    assert premier.get("api_output_estimated") is True


def test_les_totaux_de_session_egalent_la_somme_des_appels_journalises():
    """Totaux (pied de conversation, statut CLI) et journal par appel (/turns, /costs) ne
    peuvent pas diverger : ils sont écrits au même endroit, une fois par appel."""
    tour_outils = f"Un.\n<tool_calls>\n{METH}\n</tool_calls>"
    result = bouzecode(["compte"], mock_api=[tour_outils, tour_outils, "trois."])

    appels = _appels(result)
    state = result.state
    assert state.total_input_tokens == sum(a["api_input_tokens"] for a in appels)
    assert state.total_output_tokens == sum(a["api_output_tokens"] for a in appels)
    assert len(appels) == len(result.recorded_requests)


def _sse_avec_usage(texte: str, input_tokens: int, cache_write: int, sortie: int) -> str:
    import json as _json

    def ev(nom, data):
        return f"event: {nom}\ndata: {_json.dumps(data)}\n\n"
    return "".join([
        ev("message_start", {"type": "message_start", "message": {
            "id": "m", "type": "message", "role": "assistant", "content": [], "model": "x",
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 1,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": cache_write}}}),
        ev("content_block_start", {"type": "content_block_start", "index": 0,
                                   "content_block": {"type": "text", "text": ""}}),
        ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                   "delta": {"type": "text_delta", "text": texte}}),
        ev("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ev("message_delta", {"type": "message_delta",
                             "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                             "usage": {"output_tokens": sortie}}),
        'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ])


# Entrée brute 1050 si l'endpoint inclut l'écriture, 50 s'il l'exclut : même grandeur attendue.
@pytest.mark.parametrize(("inclut_ecriture", "entree_brute"), [("1", 1050), ("0", 50)])
def test_l_entree_comptee_inclut_toujours_l_ecriture_de_cache(monkeypatch, inclut_ecriture,
                                                               entree_brute):
    """Selon l'endpoint, input_tokens inclut ou non l'écriture de cache (le gateway l'exclut, mesuré le
    2026-09-29, bien qu'annoncé inclusif). La session doit porter la même grandeur dans les deux cas
    — sinon le coût (calc_cost retire l'écriture de l'entrée) et le taux de cache divergent d'un endpoint à
    l'autre."""
    monkeypatch.setenv("BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE", inclut_ecriture)
    result = bouzecode(["salut"], mock_api=[{"raw_sse": _sse_avec_usage("Bonjour.", entree_brute, 1000, 3)}])

    appel = _appels(result)[0]
    assert appel["api_input_tokens"] == 1050
    assert appel["api_cache_create"] == 1000
    assert appel["api_output_tokens"] == 3


def test_apres_le_lot_le_texte_invente_est_ignore_mais_la_sortie_est_comptee():
    """Après `</tool_calls>`, un modèle peut continuer et inventer le résultat de son propre
    appel. Ce texte ne doit JAMAIS entrer dans la conversation — mais sa génération a été
    facturée : output_tokens (annoncé à la toute fin du flux) doit être compté quand même."""
    lot = f"Je note.\n<tool_calls>\n{METH}\n</tool_calls>"
    invente = '\n<tool_result id="m1">RÉSULTAT INVENTÉ</tool_result>\nEt la suite inventée.'
    result = bouzecode(["note ça"], mock_api=[{"chunks": [lot, invente]}, "fin."])

    assert not any("INVENTÉ" in str(m.get("content", "")) for m in result.messages)
    premier = _appels(result)[0]
    assert premier["api_output_tokens"] == _sortie_annoncee(lot + invente)
    assert not premier.get("api_output_estimated")
