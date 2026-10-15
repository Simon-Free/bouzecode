# [desc] Agent Rundeck qui répond en prose sans jamais appeler FinalAnswer, de bout en bout : le paquet joue le VRAI CLI contre un faux LLM scripté (faux Rundeck + vm_runner) → relances puis `final_answer_never_called`, code 4 → ticket `idle_no_delivery`, jamais livré, signalement, parent réveillé. [/desc]
"""Avant : `rapport.issue_de_l_agent` classait `text_no_tools` comme une livraison (la prose de
l'agent `-p` servait de `reponse.md`). Règle : seul FinalAnswer livre, en local comme à distance."""
from __future__ import annotations

import json
from pathlib import Path

from bouzecode.web_v2.services.work import signalements, tickets, wake
from bouzecode.web_v2.services.work.distant import suivi
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.faux_llm_refus import script_vm
from bouzecode.web_v2.tests.faux_llm_scripte import FauxLlmScripte
from bouzecode.web_v2.tests.test_rundeck_bout_en_bout import (  # noqa: F401
    PARENT, _lancer, depot, horloge, reveils, rundeck)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import client  # noqa: F401

RAISON = "final_answer_never_called"


def test_une_prose_sans_finalanswer_sur_rundeck_n_est_jamais_livree(
        client, depot, rundeck, horloge, reveils, tmp_path):  # noqa: F811
    with FauxLlmScripte(["Voila, b.txt est ajoute."]) as llm:
        ticket_id = _lancer(client, script_vm(llm, tmp_path / "home_vm", tmp_path))["ticket_id"]
        assert len(llm.requetes) == 11  # la prose relancée 10 fois, puis clôture forcée

    wake.tick()
    horloge[0] += suivi.CADENCE_S + 1
    wake.tick()

    ticket = tickets.get_ticket("demo", ticket_id)
    run, = ticket["runs"]
    assert ticket["state"] == etats.IDLE_NO_DELIVERY != etats.DELIVERED
    assert ticket["state_reason"]["code"] == RAISON
    assert run["issue"] == "echec" and run["code"] == 4 and not run.get("completed")
    assert run["close_reason"] == RAISON and "sans livrer" in run["raison"]
    dossier = Path(run["dossier_local"])
    bilan = json.loads((dossier / "resultat.json").read_text(encoding="utf-8"))
    assert bilan["close_reason"] == RAISON and bilan["final_answer"] is False
    assert not (dossier / "reponse.md").exists()  # la prose n'est jamais une réponse
    signalement, = [s for s in signalements.ouverts() if s["ticket_id"] == ticket_id]
    assert "Execution Rundeck en echec" in signalement["titre"]
    assert signalement["parents"] == [PARENT] and RAISON in signalement["detail"]
    (parent, digest), = reveils
    assert parent == PARENT and RAISON in digest and "LIVRAISON" not in digest


def test_la_classification_distante_est_celle_de_la_table_unique():
    """Plus de traitement spécial : prose -> fin sans livraison ; pas de fiche -> arrêt."""
    from bouzecode.web_v2.services.work.distant import rapport
    assert rapport.issue_de_l_agent({"close_reason": "text_no_tools"}) == (
        etats.IDLE_NO_DELIVERY, "text_no_tools")
    assert rapport.issue_de_l_agent({"close_reason": "final_answer", "final_answer": True}) == (
        etats.DELIVERED, "final_answer")
    assert rapport.issue_de_l_agent({"code": 0})[0] == etats.STOPPED
    assert "aucune fiche" in rapport.raison_d_echec({"mode": "agent"}, {}, {"code": 0})
