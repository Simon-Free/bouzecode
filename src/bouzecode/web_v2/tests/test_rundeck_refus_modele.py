# [desc] Refus du modèle sur Rundeck de bout en bout : le paquet joue le VRAI CLI contre un faux LLM qui refuse (faux Rundeck + vm_runner) → `resultat.json` porte `content_refusal` → ticket `idle_no_delivery`, jamais livré, signalement « reformule ou relance », parent réveillé. [/desc]
"""Exécution 257426 du 2026-10-06 : un refus sortait en code 0 et le run était classé livré sans
un commit. Ici toute la chaîne tourne : vm_runner (la VM, en local) lance `bouzecode -p
--result-file "$BZ_RESULTAT/reponse.md"`, rapatrie sa fiche de clôture, `distant.suivi` classe."""
from __future__ import annotations

import json
from pathlib import Path

from bouzecode.web_v2.services.work import signalements, tickets, wake
from bouzecode.web_v2.services.work.distant import suivi
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.faux_llm_refus import FauxLlmRefus, script_vm
from bouzecode.web_v2.tests.test_rundeck_bout_en_bout import (  # noqa: F401
    PARENT, _lancer, depot, horloge, reveils, rundeck)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import client  # noqa: F401


def test_un_refus_du_modele_sur_rundeck_n_est_jamais_livre(
        client, depot, rundeck, horloge, reveils, tmp_path):  # noqa: F811
    with FauxLlmRefus() as llm:
        ticket_id = _lancer(client, script_vm(llm, tmp_path / "home_vm", tmp_path))["ticket_id"]
        assert len(llm.requetes) == 1  # le faux Rundeck joue le paquet au lancement

    wake.tick()
    horloge[0] += suivi.CADENCE_S + 1
    wake.tick()

    ticket = tickets.get_ticket("demo", ticket_id)
    run, = ticket["runs"]
    assert ticket["state"] == etats.IDLE_NO_DELIVERY != etats.DELIVERED
    assert ticket["state_reason"]["code"] == "content_refusal"
    assert run["issue"] == "echec" and run["code"] == 3 and not run.get("completed")
    assert run["close_reason"] == "content_refusal" and "refuse la consigne" in run["raison"]
    bilan = json.loads((Path(run["dossier_local"]) / "resultat.json").read_text(encoding="utf-8"))
    assert bilan["close_reason"] == "content_refusal" and bilan["final_answer"] is False
    signalement, = [s for s in signalements.ouverts() if s["ticket_id"] == ticket_id]
    assert "refusé la consigne" in signalement["titre"] and signalement["parents"] == [PARENT]
    assert "reformule" in signalement["action_attendue"]
    (parent, digest), = reveils
    assert parent == PARENT and "refuse la consigne" in digest and "LIVRAISON" not in digest
    assert "refusé la consigne" in digest  # le signalement arrive avec le réveil
