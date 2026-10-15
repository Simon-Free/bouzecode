# [desc] Sous-agents du TUI en process : l'outil Agent les lance dans des fils du meme process, rend leur FinalAnswer (jamais une fin sans FinalAnswer), route messages, questions et reprises vers le bon enfant, et descend recursivement. [/desc]
"""La boucle agent est remplacee par un faux `_agent_run` (meme seam que test_subagent.py) :
chaque faux enfant suit un petit script lu dans son prompt. Le vrai LLM n'intervient pas ;
le TUI pilote de bout en bout est dans tests/ui/barre_agents/test_tui_sous_agents_e2e.py."""
from __future__ import annotations

import time

import pytest

from bouzecode.backend.agent.state import AgentState, ToolEnd, TurnDone
from bouzecode.backend.multi_agent import lancement_terminal, outil_agent, outils_enfants
from bouzecode.backend.multi_agent.en_process.fiche import ERREUR, FINI, PRINCIPAL, QUESTION
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents


def _faux_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    """Un enfant scripte par son prompt : `livre`, `prose`, `question`, `courrier`, `petit`,
    `signale` — et, en reprise, il livre ce qu'on lui a ecrit."""
    config = {**config, "_depth": depth}  # comme agent.loop.run
    state.messages.append({"role": "user", "content": prompt})
    state.total_input_tokens += 100
    state.total_output_tokens += 10
    yield TurnDone(100, 10)
    if prompt.startswith("question"):
        reponse = config["_tui_question"]("Quelle base ?", ["rec", "prod"])
        state.final_answer = f"base choisie : {reponse}"
    elif prompt.startswith("courrier"):
        while not (lettres := config["_inbox_pop"]()):
            time.sleep(0.01)
        state.final_answer = f"lu : {lettres[0]}"
    elif prompt.startswith("petit"):
        state.final_answer = outil_agent._agent_tool({"prompt": "livre petit-enfant"}, config)
    elif prompt.startswith("signale"):
        yield ToolEnd("Signaler", "Signalement s1 enregistre", inputs={
            "gravite": "alerte", "titre": "proxy 407"})
        state.final_answer = "signalé"
    elif prompt.startswith("prose"):
        state.messages.append({"role": "assistant", "content": "j'ai fini, je crois"})
        state.close_reason = "final_answer_never_called"
    else:
        state.final_answer = f"rapport de « {prompt} »"


@pytest.fixture
def tui(monkeypatch):
    """La config du principal telle que le REPL interactif la pose."""
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _faux_run)
    monkeypatch.setattr("bouzecode.backend.multi_agent.en_process.execution._sauver",
                        lambda fiche: None)
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    return registre, {"_tui_agents": registre, "model": "claude-opus-5", "_depth": 0}


def _attendre_etat(registre, agent_id, etat):
    for _ in range(100):
        fiche = registre.fiche(agent_id)
        if fiche is not None and fiche.etat == etat:
            return fiche
        registre.attendre_changement(0.05)
    raise AssertionError(f"{agent_id} jamais {etat} : {registre.fiche(agent_id)}")


def test_le_parent_recoit_le_final_answer_de_son_enfant(tui):
    registre, config = tui
    rapport = outil_agent._agent_tool({"prompt": "livre le module", "name": "alpha"}, config)
    assert rapport == "[Agent: alpha (general-purpose)]\n\nrapport de « livre le module »"
    fiche = registre.sous_agents()[0]
    assert fiche.etat == FINI and fiche.parent_id == PRINCIPAL
    assert fiche.tokens()["entree"] == 100 and fiche.fin is not None


def test_un_enfant_qui_finit_sans_final_answer_est_un_echec_explicite(tui):
    registre, config = tui
    rapport = outil_agent._agent_tool({"prompt": "prose seulement"}, config)
    assert "Error: le sous-agent s'est arrêté SANS FinalAnswer" in rapport
    assert "j'ai fini, je crois" not in rapport
    assert registre.sous_agents()[0].etat == ERREUR


def test_en_fond_la_main_revient_et_check_agent_result_attend_le_rapport(tui):
    registre, config = tui
    lance = outil_agent._agent_tool({"prompt": "courrier", "background": True}, config)
    fiche = registre.sous_agents()[0]
    assert lance.startswith(f"Task ID: {fiche.id}") and fiche.actif
    assert config["_bg_agent_launched"] is True
    assert "mis en file" in registre.envoyer(fiche.id, "le README")
    verdict = outils_enfants._check_agent_result({"task_id": fiche.id, "wait": True}, config)
    assert "lu : le README" in verdict


def test_la_reponse_tapee_dans_la_vue_debloque_la_question_du_bon_enfant(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "question base", "background": True, "name": "q"}, config)
    outil_agent._agent_tool({"prompt": "courrier", "background": True, "name": "c"}, config)
    question, courrier = registre.sous_agents()
    _attendre_etat(registre, question.id, QUESTION)
    assert question.question.texte == "Quelle base ?"
    registre.envoyer(question.id, "1")
    assert _attendre_etat(registre, question.id, FINI).resultat == "base choisie : rec"
    assert courrier.actif  # l'autre enfant n'a rien recu
    registre.interrompre(courrier.id)


def test_ecrire_a_un_enfant_fini_le_fait_reprendre_sur_sa_conversation(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "livre v1", "name": "alpha"}, config)
    fiche = registre.sous_agents()[0]
    assert "reprend" in registre.envoyer(fiche.id, "livre v2")
    _attendre_etat(registre, fiche.id, FINI)
    for _ in range(100):
        if fiche.resultat:
            break
        registre.attendre_changement(0.05)
    assert fiche.resultat == "rapport de « livre v2 »"
    assert [m["content"] for m in fiche.state.messages] == ["livre v1", "livre v2"]


def test_un_sous_agent_lance_ses_propres_enfants_visibles_sous_lui(tui):
    registre, config = tui
    rapport = outil_agent._agent_tool({"prompt": "petit", "name": "parent"}, config)
    parent, petit = registre.arbre()[1:]
    assert (petit.parent_id, petit.profondeur, parent.profondeur) == (parent.id, 2, 1)
    assert "rapport de « livre petit-enfant »" in rapport


def test_la_profondeur_reste_bornee(tui):
    registre, config = tui
    config.update(_depth=4, max_agent_depth=4)
    assert "profondeur maximale" in outil_agent._agent_tool({"prompt": "livre"}, config)
    assert registre.sous_agents() == []


def test_signaler_d_un_enfant_remonte_dans_la_barre(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "signale", "name": "veilleur"}, config)
    assert registre.sous_agents()[0].alertes == ["[alerte] proxy 407"]
    assert registre.alertes_nouvelles() == ["⚑ [alerte] proxy 407 — sous-agent veilleur"]


def test_le_mode_fenetre_reste_disponible_par_option(tui, monkeypatch):
    registre, config = tui
    fenetres = []
    monkeypatch.setattr(outil_agent, "_is_terminal_mode", lambda: True)
    monkeypatch.setattr(lancement_terminal, "_spawn_terminal_agent",
                        lambda params, cfg: fenetres.append(params["prompt"]) or "fenêtre")
    config["subagents_window"] = True
    assert outil_agent._agent_tool({"prompt": "livre"}, config) == "fenêtre"
    assert fenetres == ["livre"] and registre.sous_agents() == []


def test_chaque_sous_agent_a_sa_propre_session_sur_disque(monkeypatch, tmp_path):
    """Sa conversation est ecrite a part (daily/<date>/session_*_<id>.json), pas dans celle
    du principal."""
    import json
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _faux_run)
    monkeypatch.setattr("bouzecode.backend.core.config.DAILY_DIR", tmp_path)
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    outil_agent._agent_tool({"prompt": "livre"}, {"_tui_agents": registre, "model": "m"})
    fiche = registre.sous_agents()[0]
    sessions = list(tmp_path.glob(f"*/session_*_{fiche.id}.json"))
    assert [str(s) for s in sessions] == [fiche.chemin_session]
    assert json.loads(sessions[0].read_text(encoding="utf-8"))["messages"][0]["content"] == "livre"
