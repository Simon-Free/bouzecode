# [desc] ResetContext sur des appels réels (faux serveur Anthropic) : la note réécrite casse le préfixe caché une fois, puis les appels suivants relisent en cache la nouvelle note (append-only à nouveau). [/desc]
"""Après ResetContext, le préfixe redevient stable.

La réécriture de la note invalide le cache une fois (accepté). On vérifie sur les corps de
requête que le vrai pipeline (dispatch → client Anthropic) envoie à un faux serveur local que,
dès l'appel suivant, la partie cachée d'un appel est reprise à l'octet par le suivant.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers.backends import dispatch
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.context_manager.methodology import append_user_msg_to_methodology
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.tools.registration import execute_tool
from tests import cache_conversation_helpers
from tests.backend.methodology.cache.test_notes_de_contexte_empilees import _cache
from tests.mock_anthropic_server import start_mock_anthropic

OUTILS = [{"name": "Bash", "description": "d", "input_schema": {}}]
TRAVAIL = "constat : le bail expire trop tôt (lease.py L42)"


@pytest.fixture
def serveur(monkeypatch):
    url, app = start_mock_anthropic(["ok"] * 5)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(cache_conversation_helpers, "LIVE_API_ALLOWED", True)  # localhost
    return app


def _appel(state: AgentState, serveur, demande: str) -> dict:
    config = {"model": "claude-opus-5", "_context_state": state.context_state}
    list(dispatch.stream(config["model"], "Noyau stable.", [
        {"role": "user", "content": demande, "_demande_utilisateur": True},
        {"role": "assistant", "content": ".", "tool_calls": [
            {"id": "t1", "name": "Bash", "input": {"command": "x"}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "Bash", "content": "ok"}], OUTILS, config))
    return serveur.recorded_calls[-1]


def test_apres_reset_les_appels_suivants_relisent_le_prefixe_en_cache(serveur, tmp_path):
    state = AgentState()
    state.turn_count = 1  # comme dans la boucle : chaque ajout porte son tampon « ### T<n> »
    outils = {"_context_state": state.context_state, "_state": state,
              "_session_file": str(tmp_path / "e2e.session.json")}
    append_user_msg_to_methodology(state.context_state, "Corrige le bug de bail.")
    execute_tool("Methodology", {"content": TRAVAIL}, "accept-all", config=outils)
    avant = [_appel(state, serveur, "Corrige le bug de bail.") for _ in range(2)]
    assert _cache(avant[1])[0].startswith(_cache(avant[0])[1])  # base : préfixe stable

    nouvelle_demande = "Autre chose : écris la doc de la CLI."
    append_user_msg_to_methodology(state.context_state, nouvelle_demande)
    reponse = execute_tool("ResetContext", {"reason": "doc CLI sans lien avec le bail"},
                           "accept-all", config=outils)
    assert "archived to" in reponse
    reset = _appel(state, serveur, nouvelle_demande)
    state.turn_count = 2
    execute_tool("Methodology", {"content": "plan : lister les commandes"}, "accept-all",
                 config=outils)
    apres = [_appel(state, serveur, nouvelle_demande) for _ in range(2)]

    # (1) la réécriture casse le préfixe une fois : le travail archivé n'est plus envoyé.
    assert not _cache(reset)[0].startswith(_cache(avant[1])[1])
    assert TRAVAIL in _cache(avant[1])[1]
    assert all(TRAVAIL not in _cache(r)[0] for r in (reset, *apres))
    # (2) la nouvelle note est dans la partie cachée dès l'appel du reset, et y reste.
    note_reinitialisee = "## Contexte archivé @"
    assert all(note_reinitialisee in _cache(r)[1] for r in (reset, *apres))
    # (3) puis le préfixe redevient stable : chaque appel relit à l'octet le cache du précédent.
    assert _cache(apres[0])[0].startswith(_cache(reset)[1])
    assert _cache(apres[1])[0].startswith(_cache(apres[0])[1])
    assert state.context_state.notes[METHODOLOGY_NOTE].endswith("plan : lister les commandes")
