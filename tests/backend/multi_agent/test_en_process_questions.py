# [desc] Questions des sous-agents du TUI : elles remontent au PARENT (pas seulement a l'utilisateur), qui y repond par MessageAgent(question=N) ou la relaie par AskUserQuestion ; parent parti → l'ancetre suivant ; la premiere reponse (parent ou utilisateur) l'emporte. [/desc]
"""Faux `_agent_run` (meme seam que test_en_process_execution) : parents et enfants suivent
un script lu dans leur prompt, mais les outils (Agent, MessageAgent, CheckAgentResult), la
voie `_tui_question` (ce qu'appelle AskUserQuestion dans un sous-agent) et le registre sont
les vrais. Le vrai REPL reveille par une question : tests/ui/barre_agents/test_tui_sous_agents_e2e.py."""
from __future__ import annotations

import re
import time

import pytest

from bouzecode.backend.agent.state import AgentState, TurnDone
from bouzecode.backend.multi_agent import outil_agent, outils_enfants
from bouzecode.backend.multi_agent.en_process import questions
from bouzecode.backend.multi_agent.en_process.fiche import FINI, PRINCIPAL, QUESTION
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents


def _lire_avis(config) -> tuple[str, int, str]:
    """Le parent attend l'avis de question dans sa boite ; rend (id enfant, numero, texte)."""
    while not (lettres := config["_inbox_pop"]()):
        time.sleep(0.01)
    avis = lettres[0]
    return re.search(r"\(id (\w+)\)", avis)[1], int(re.search(r"n°(\d+)", avis)[1]), avis


def _faux_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    config = {**config, "_depth": depth}
    state.messages.append({"role": "user", "content": prompt})
    yield TurnDone(10, 1)
    if prompt.startswith("question"):  # l'enfant demande (AskUserQuestion du sous-agent)
        state.final_answer = "base choisie : " + config["_tui_question"]("Quelle base ?",
                                                                         ["rec", "prod"])
    elif prompt.startswith("repond"):  # le parent sait : il repond lui-meme
        outil_agent._agent_tool({"prompt": "question", "name": "enfant", "background": True},
                                config)
        enfant, numero, _avis = _lire_avis(config)
        verdict = outils_enfants._message_agent(
            {"ticket_id": enfant, "text": "2", "question": numero}, config)
        rapport = outils_enfants._check_agent_result({"task_id": enfant, "wait": True}, config)
        state.final_answer = f"{verdict}\n{rapport}"
    elif prompt.startswith("relaie"):  # le parent ne sait pas : il demande a SON parent
        outil_agent._agent_tool({"prompt": "question", "name": "enfant", "background": True},
                                config)
        enfant, numero, _avis = _lire_avis(config)
        reponse = config["_tui_question"]("L'enfant demande : Quelle base ?", [])
        outils_enfants._message_agent({"ticket_id": enfant, "text": reponse,
                                       "question": numero}, config)
        rapport = outils_enfants._check_agent_result({"task_id": enfant, "wait": True}, config)
        state.final_answer = rapport
    elif prompt.startswith("abandonne"):  # le parent rend la main sans attendre son enfant
        outil_agent._agent_tool({"prompt": "question", "name": "orphelin", "background": True},
                                config)
        state.final_answer = "parti"
    else:
        state.final_answer = f"rapport de « {prompt[:40]} »"


@pytest.fixture
def tui(monkeypatch):
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _faux_run)
    monkeypatch.setattr("bouzecode.backend.multi_agent.en_process.execution._sauver",
                        lambda fiche: None)
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    return registre, {"_tui_agents": registre, "model": "claude-opus-5", "_depth": 0}


def _attendre(condition, quoi: str):
    for _ in range(200):
        if condition():
            return
        time.sleep(0.025)
    raise AssertionError(f"jamais : {quoi}")


def _enfant_en_question(registre, nom: str):
    _attendre(lambda: any(f.description == nom and f.etat == QUESTION
                          for f in registre.sous_agents()), f"{nom} pose sa question")
    return next(f for f in registre.sous_agents() if f.description == nom)


def test_le_parent_recoit_la_question_de_son_enfant_et_y_repond_lui_meme(tui):
    registre, config = tui
    rapport = outil_agent._agent_tool({"prompt": "repond", "name": "parent"}, config)
    assert "réponse transmise" in rapport and "base choisie : prod" in rapport
    assert registre.courrier(PRINCIPAL) == []  # main n'a jamais ete derange


def test_l_avis_dit_au_parent_comment_repondre_ou_relayer(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "question", "name": "enfant", "background": True}, config)
    enfant = _enfant_en_question(registre, "enfant")
    _attendre(lambda: questions.a_traiter(registre, PRINCIPAL), "main a une question a traiter")
    avis = registre.courrier(PRINCIPAL)[0]
    assert "Quelle base ?" in avis and "[1] rec · [2] prod" in avis
    assert f"MessageAgent(ticket_id='{enfant.id}', text='<réponse>', question=1)" in avis
    assert "AskUserQuestion (elle va à l'utilisateur)" in avis
    outils_enfants._message_agent({"ticket_id": enfant.id, "text": "rec", "question": 1}, config)
    _attendre(lambda: enfant.etat == FINI, "l'enfant livre")
    assert enfant.resultat == "base choisie : rec"


def test_le_parent_qui_ne_sait_pas_relaie_a_main_puis_transmet_la_reponse(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "relaie", "name": "parent", "background": True}, config)
    parent = _enfant_en_question(registre, "parent")
    #  La question de l'enfant est chez le parent ; celle du parent (le relais) chez main.
    assert "L'enfant demande : Quelle base ?" in registre.courrier(PRINCIPAL)[0]
    assert "elle va à ton propre parent" not in registre.courrier(PRINCIPAL)[0]
    outils_enfants._message_agent({"ticket_id": "parent", "text": "prod",
                                   "question": parent.question.numero}, config)
    _attendre(lambda: parent.etat == FINI, "le parent livre")
    assert "base choisie : prod" in parent.resultat


def test_l_utilisateur_repond_le_premier_et_le_parent_l_apprend(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "question", "name": "enfant", "background": True}, config)
    enfant = _enfant_en_question(registre, "enfant")
    assert "réponse transmise" in registre.envoyer(enfant.id, "1")  # depuis la vue de l'enfant
    _attendre(lambda: enfant.etat == FINI, "l'enfant livre")
    assert enfant.resultat == "base choisie : rec"
    #  L'avis encore non lu est retire : main au repos n'est pas reveille pour rien.
    assert registre.courrier(PRINCIPAL) == [] and not questions.a_traiter(registre, PRINCIPAL)
    retour = outils_enfants._message_agent({"ticket_id": enfant.id, "text": "prod",
                                            "question": 1}, config)
    assert "DÉJÀ répondue par l'utilisateur (« rec »)" in retour and "PAS transmis" in retour


def test_avis_deja_lu_le_parent_est_prevenu_que_l_utilisateur_a_repondu(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "question", "name": "enfant", "background": True}, config)
    enfant = _enfant_en_question(registre, "enfant")
    _attendre(lambda: registre.courrier(PRINCIPAL), "avis chez main")
    registre.relever(PRINCIPAL)  # main l'a lu a sa frontiere de lot
    registre.envoyer(enfant.id, "prod")
    _attendre(lambda: enfant.etat == FINI, "l'enfant livre")
    assert registre.courrier(PRINCIPAL) == [
        "[Question n°1 : l'utilisateur y a déjà répondu (« prod ») — n'y réponds plus.]"]
    assert not questions.a_traiter(registre, PRINCIPAL)


def test_un_enfant_dont_le_parent_est_parti_remonte_sa_question_a_main(tui):
    registre, config = tui
    outil_agent._agent_tool({"prompt": "abandonne", "name": "parent"}, config)
    orphelin = _enfant_en_question(registre, "orphelin")
    _attendre(lambda: any(f"(id {orphelin.id})" in a for a in registre.courrier(PRINCIPAL)),
              "la question de l'orphelin arrive chez main")
    outils_enfants._message_agent({"ticket_id": "orphelin", "text": "rec",
                                   "question": orphelin.question.numero}, config)
    _attendre(lambda: orphelin.etat == FINI, "l'orphelin livre")
    assert orphelin.resultat == "base choisie : rec"


def test_une_permission_ne_remonte_jamais_au_parent(tui):
    """Seul l'utilisateur accorde une permission : elle reste dans la barre."""
    registre, config = tui
    outil_agent._agent_tool({"prompt": "livre", "name": "x"}, config)
    fiche = registre.sous_agents()[0]
    import threading
    reponses = []
    fil = threading.Thread(target=lambda: reponses.append(registre.poser_question(
        fiche.id, "Autoriser : rm ?", ["oui", "non"], False)))
    fil.start()
    _attendre(lambda: fiche.question is not None, "permission posee")
    assert registre.courrier(PRINCIPAL) == []
    registre.envoyer(fiche.id, "2")
    fil.join(5)
    assert reponses == ["non"]
