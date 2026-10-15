# [desc] Fleet et MessageAgent dans le TUI : proposes au modele des qu'une flotte en process existe (et masques hors web ET hors TUI), MessageAgent route vers le bon sous-agent (question, file, reprise, arret), Fleet liste l'arbre et interrompt. [/desc]
"""Faux `_agent_run` (comme test_en_process_execution) ; aucun LLM, aucun serveur."""
from __future__ import annotations

import time

import pytest

from bouzecode.backend.agent.state import AgentState, TurnDone
from bouzecode.backend.core import tool_registry
from bouzecode.backend.multi_agent import outil_agent, outils_enfants, outils_flotte
from bouzecode.backend.multi_agent.en_process.fiche import ANNULE, FINI, QUESTION
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents


def _faux_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    state.messages.append({"role": "user", "content": prompt})
    state.total_input_tokens += 1000
    yield TurnDone(1000, 10)
    if prompt.startswith("question"):
        state.final_answer = "choix : " + config["_tui_question"]("Laquelle ?", ["a", "b"])
    elif prompt.startswith("attente"):
        while not cancel_check():  # travaille jusqu'a l'interruption
            time.sleep(0.01)
    else:
        state.final_answer = f"rapport de « {prompt} »"


@pytest.fixture
def tui(monkeypatch):
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _faux_run)
    monkeypatch.setattr("bouzecode.backend.multi_agent.en_process.execution._sauver",
                        lambda fiche: None)
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    monkeypatch.setattr(tool_registry, "_flotte_locale", False)
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    return registre, {"_tui_agents": registre, "model": "claude-opus-5"}


def _noms_proposes() -> set:
    import bouzecode.backend.tools  # noqa: F401 — registre complet
    return {s["name"] for s in tool_registry.get_tool_schemas()}


def test_fleet_et_message_agent_ne_sont_proposes_qu_avec_une_flotte(tui):
    """Hors web et hors TUI : masques. TUI interactif (flotte locale) : proposes."""
    assert not {"Fleet", "MessageAgent"} & _noms_proposes()
    tool_registry.activer_flotte_locale(True)
    assert {"Fleet", "MessageAgent"} <= _noms_proposes()


def test_message_agent_repond_a_la_question_du_bon_enfant(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "question", "name": "q", "background": True}, config)
    fiche = registre.sous_agents()[0]
    while fiche.etat != QUESTION:
        registre.attendre_changement(0.1)
    retour = outils_enfants._message_agent({"ticket_id": "q", "text": "2"}, config)
    assert "réponse transmise" in retour
    outils_enfants._check_agent_result({"task_id": fiche.id, "wait": True}, config)
    assert fiche.resultat == "choix : b"


def test_message_agent_a_un_enfant_fini_le_relance(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "livre v1", "name": "alpha"}, config)
    fiche = registre.sous_agents()[0]
    assert "reprend" in outils_enfants._message_agent({"ticket_id": fiche.id, "text": "livre v2"},
                                                   config)
    outils_enfants._check_agent_result({"task_id": fiche.id, "wait": True}, config)
    assert fiche.etat == FINI and fiche.resultat == "rapport de « livre v2 »"


def test_message_agent_arreter_interrompt_sans_livrer(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "attente", "name": "long", "background": True}, config)
    fiche = registre.sous_agents()[0]
    retour = outils_enfants._message_agent({"ticket_id": "long", "text": "stop",
                                         "arreter": True}, config)
    assert "SANS livrer" in retour
    outils_enfants._check_agent_result({"task_id": fiche.id, "wait": True}, config)
    assert fiche.etat == ANNULE and fiche.resultat.startswith("Error:")


def test_fleet_liste_l_arbre_et_kill_interrompt(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "livre", "name": "alpha"}, config)
    outil_agent._agent_tool({"prompt": "attente", "name": "beta", "background": True}, config)
    liste = outils_flotte._fleet_tool({"action": "list"}, config)
    assert liste.startswith("2 sous-agent(s) en process")
    assert "✓ fini | general-purpose | alpha | parent=main | in 1000 out 0" in liste
    beta = next(f for f in registre.sous_agents() if f.description == "beta")
    assert "interrompu" in outils_flotte._fleet_tool({"action": "kill", "agent_id": "beta"}, config)
    outils_enfants._check_agent_result({"task_id": beta.id, "wait": True}, config)
    assert beta.etat == ANNULE
    assert "introuvable" in outils_flotte._fleet_tool({"action": "kill", "agent_id": "x"}, config)


def test_hors_web_et_hors_tui_le_message_reste_explicite(tui):
    _registre, config = tui
    config.pop("_tui_agents")
    assert "n'est disponible qu'en mode bouzeui web" in outils_enfants._message_agent(
        {"ticket_id": "x", "text": "y"}, config)
