# [desc] Refus du modèle en LOCAL de bout en bout : vrai CLI contre un faux LLM qui refuse → session `content_refusal` → watchdog → ticket `idle_no_delivery` (jamais `delivered`), signalement « reformule ou relance », parent réveillé avec la raison. [/desc]
"""Vrai process bouzecode (`-p --session-file` dans le parc isolé), vrai store, vrai watchdog
(`wake.tick`) ; aucun mock. Le second test passe par le hook de fin de run (`fin_de_run`)."""
from __future__ import annotations

import subprocess

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import constats, signalements, tickets, wake
from bouzecode.web_v2.services.work.api_tickets import fin_de_run
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.faux_llm_refus import FauxLlmRefus, commande_cli, environnement_cli
from bouzecode.web_v2.tests.test_constats_watchdog import SLUG, _en_cours, _fiche, projet  # noqa: F401
from bouzecode.web_v2.tests.test_rundeck_bout_en_bout import PARENT, reveils  # noqa: F401

AGENT = "refuslocal01"


def _signalement_du(ticket_id: str) -> dict:
    signalement, = [s for s in signalements.ouverts() if s["ticket_id"] == ticket_id]
    return signalement


def test_un_refus_du_modele_finit_non_livre_signale_et_reveille_le_parent(tmp_path, reveils):  # noqa: F811
    ticket = _en_cours(AGENT, parent=PARENT)
    session = agent_fiche.AGENTS_DIR / f"{AGENT}.session.json"
    with FauxLlmRefus() as llm:
        sortie = subprocess.run(
            commande_cli(str(tmp_path / "reponse.md"), "--cwd", str(tmp_path),
                         "--session-file", str(session)),
            env=environnement_cli(llm, tmp_path / "home"), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=100)
    assert sortie.returncode == 3, sortie.stderr[-2000:]
    _fiche(AGENT, ticket["id"])  # fiche d'un agent mort ; la session est celle du CLI

    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()

    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.IDLE_NO_DELIVERY != etats.DELIVERED
    assert frais["state_reason"]["code"] == "content_refusal"
    assert not frais["runs"][0].get("completed")
    signalement = _signalement_du(ticket["id"])
    assert signalement["gravite"] == "alerte" and signalement["parents"] == [PARENT]
    assert "refusé la consigne" in signalement["titre"]
    assert "reformule" in signalement["action_attendue"] and "relance" in signalement["action_attendue"]
    (parent, digest), = reveils
    assert parent == PARENT and ticket["id"] in digest and "LIVRÉ" not in digest
    assert "content_refusal" in digest and "refusé la consigne" in digest


def test_le_hook_de_fin_classe_un_refus_comme_une_fin_sans_livraison():
    ticket = _en_cours(AGENT)
    reponse = fin_de_run.terminer(SLUG, ticket["id"], AGENT, "content_refusal")
    assert (reponse["state"], reponse["state_reason"]["code"]) == (etats.IDLE_NO_DELIVERY,
                                                                   "content_refusal")
    assert "reformule" in _signalement_du(ticket["id"])["action_attendue"]
    fin_de_run.terminer(SLUG, ticket["id"], AGENT, "content_refusal")  # hook rejoué
    assert len([s for s in signalements.ouverts() if s["ticket_id"] == ticket["id"]]) == 1
