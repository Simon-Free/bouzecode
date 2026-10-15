# [desc] Un agent clos pour de bon, ou dont l'arrêt a été demandé, n'est pas relancé par le compte rendu de ses propres enfants : le compte rendu est noté sur son ticket, où son parent le lit. [/desc]
"""Essai DeepSeek du 2026-09-25. La racine 6bafe9cd a lancé 40ea29e4 (coder, ticket a139daa2),
qui a lancé 85ce949a (ticket e7ca0970). 85ce949a a livré à 01:28 ; 40ea29e4 l'a lu
(CheckAgentResult wait) puis, sur demande d'arrêt de la racine, a rendu sa FinalAnswer à
02:02. Le réveil l'a aussitôt relancé avec « Tous tes enfants ont fini leur tour » : 16 tours
de plus, jusqu'au kill de 02:14, pendant que CheckAgentResult avait annoncé « fini, livré ».

Tickets, fiches d'agents et sessions sont écrits sur disque comme le runner les écrit ; seul
`runner.continue_agent` (qui lancerait un process) est remplacé par un espion."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import arret, constats, enfants, projects, tickets, wake
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    SLUG, client, ecrire_agent,
)
from bouzecode.web_v2.runtime.runner import agent_reprise

RACINE = "6bafe9cd5ee7"
ENFANT = "40ea29e4253a"
PETIT_ENFANT = "85ce949a46cc"


@pytest.fixture()
def reveils(monkeypatch, tmp_path):
    """Le projet est ouvert ; chaque réveil est noté au lieu de lancer un process."""
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": SLUG, "name": SLUG,
                                                   "path": str(tmp_path)}]), encoding="utf-8")
    monkeypatch.setattr(wake, "WAKE_STATE_PATH", tmp_path / "wake_state.json")
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, message: notes.append((agent.agent_id, message)) or agent)
    return notes


def _ticket(titre: str, parent: str, agent_id: str) -> dict:
    ticket = tickets.create_ticket(SLUG, titre, titre)
    tickets.poser(SLUG, ticket, parent=parent)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    return tickets.get_ticket(SLUG, ticket["id"])


def _clos(agent_id: str, ticket_id: str, **session) -> None:
    """L'agent a rendu sa FinalAnswer et son process est fini (hook de fin : le run est
    terminé) ; `session` complète son JSON."""
    ecrire_agent(agent_id, ticket_id=ticket_id, final={"answer": "rapport rendu"})
    chemin = agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"
    data = json.loads(chemin.read_text(encoding="utf-8"))
    chemin.write_text(json.dumps({**data, **session}), encoding="utf-8")
    constats.fin_de_run(SLUG, ticket_id, agent_id, "final_answer")


def _famille(**session_de_l_enfant) -> tuple[dict, dict]:
    """Racine vivante → enfant clos → petit-enfant qui a livré."""
    ecrire_agent(RACINE, vivant=True, ipc="running")
    enfant = _ticket("refonte du scraper", RACINE, ENFANT)
    petit = _ticket("rapport de mesure", ENFANT, PETIT_ENFANT)
    _clos(PETIT_ENFANT, petit["id"])
    _clos(ENFANT, enfant["id"], **session_de_l_enfant)
    return enfant, petit


def test_un_enfant_clos_pour_de_bon_n_est_pas_relance_par_le_rapport_de_son_enfant(reveils):
    """Clôture sans enfant actif : le compte rendu du petit-enfant est noté, rien n'est relancé,
    et la racine lit la même chose partout : l'enfant a livré, avec la note."""
    enfant, petit = _famille(cloture_en_attente_des_enfants=False)

    wake.process_wakes()
    wake.process_wakes()

    assert reveils == []
    note = tickets.get_ticket(SLUG, enfant["id"])["comptes_rendus_sans_relance"]
    assert [n["ticket"] for n in note] == [petit["id"]]
    vue = next(f for f in enfants.enfants_de(RACINE) if f["ticket_id"] == enfant["id"])
    assert vue["etat"] == enfants.LIVRE and not vue["actif"]
    assert petit["id"] in vue["issue"] and "sans le relancer" in vue["issue"]
    commentaires = [c["text"] for c in tickets.get_ticket(SLUG, enfant["id"])["comments"]]
    assert len([c for c in commentaires if c.startswith("Réveil évité")]) == 1


def test_un_manager_qui_a_clos_pour_attendre_ses_enfants_est_reveille(reveils):
    """Contrôle : clore pour attendre (manager) reste le protocole — le digest le relance."""
    _famille(cloture_en_attente_des_enfants=True)

    wake.process_wakes()

    assert [agent for agent, _ in reveils] == [ENFANT]
    assert "Tous tes enfants ont fini leur tour" in reveils[0][1]


def test_une_session_d_avant_le_champ_garde_l_ancien_reveil(reveils):
    """Contrôle : une session sans l'information (clôture antérieure) est réveillée comme avant."""
    _famille()

    wake.process_wakes()

    assert [agent for agent, _ in reveils] == [ENFANT]


def test_une_racine_close_sans_attendre_garde_son_reveil(reveils):
    """Une tâche lancée du Bureau (parent `dispatcher:manual`) a délégué puis clos après que le
    harnais a attendu ses enfants : personne au-dessus d'elle ne lirait la note, le réveil
    reste — c'est lui qui lui fait intégrer le travail de ses enfants (E2E manager-worktree)."""
    racine = _ticket("coordonner deux lots", "dispatcher:manual", ENFANT)
    petit = _ticket("rapport de mesure", ENFANT, PETIT_ENFANT)
    _clos(PETIT_ENFANT, petit["id"])
    _clos(ENFANT, racine["id"], cloture_en_attente_des_enfants=False)

    wake.process_wakes()

    assert [agent for agent, _ in reveils] == [ENFANT]
    assert "comptes_rendus_sans_relance" not in tickets.get_ticket(SLUG, racine["id"])

def test_un_agent_dont_l_arret_a_ete_demande_n_est_jamais_reveille(reveils):
    """Même un manager qui attendait : son parent lui a demandé d'arrêter."""
    enfant, _ = _famille(cloture_en_attente_des_enfants=True)
    arret.poser(SLUG, tickets.get_ticket(SLUG, enfant["id"]), "parent (MessageAgent)")

    wake.process_wakes()

    assert reveils == []
    assert tickets.get_ticket(SLUG, enfant["id"])["comptes_rendus_sans_relance"]


def test_message_agent_arreter_pose_la_demande_et_une_nouvelle_consigne_la_leve(client, reveils):
    """`MessageAgent(arreter=true)` : l'enfant lit la demande d'arrêt, le ticket la garde ;
    un message ordinaire ensuite (nouvelle mission) la retire."""
    enfant, _ = _famille(cloture_en_attente_des_enfants=True)

    arreter = client.post(f"/api/projects/{SLUG}/tickets/{enfant['id']}/messages", json={
        "text": "tu es redondant", "arreter": True, "origine": "parent"})
    assert arreter.status_code == 200
    assert arret.demande(tickets.get_ticket(SLUG, enfant["id"]), SLUG)
    assert reveils[-1][1].startswith("DEMANDE D'ARRÊT de ton parent")

    client.post(f"/api/projects/{SLUG}/tickets/{enfant['id']}/messages",
                json={"text": "reprends X", "origine": "parent"})
    assert not arret.demande(tickets.get_ticket(SLUG, enfant["id"]), SLUG)



def test_une_relance_par_l_utilisateur_leve_l_arret_pose_par_un_kill(client, reveils, monkeypatch):
    """Arrêté depuis l'interface puis relancé à la main (POST /api/agents/<id>/messages) : c'est une nouvelle
    mission, le réveil par ses enfants doit de nouveau pouvoir le relancer."""
    from bouzecode.web_v2.services.work import dispatch
    monkeypatch.setattr(dispatch, "rehome_agent_cwd", lambda agent: None)
    enfant, _ = _famille(cloture_en_attente_des_enfants=True)
    arret.poser(SLUG, tickets.get_ticket(SLUG, enfant["id"]), "utilisateur")

    reponse = client.post(f"/api/agents/{ENFANT}/messages", json={"mode": "refuse", "text": "reprends"})

    assert reponse.status_code == 200, reponse.get_json()
    assert not arret.demande(tickets.get_ticket(SLUG, enfant["id"]), SLUG)
    assert reveils[-1] == (ENFANT, "reprends")

# ── Ce que l'agent déclare en clôturant ─────────────────────────────────────

@pytest.mark.parametrize("profil, enfant_vivant, attend", [
    ("", False, False),         # un coder dont l'enfant a livré : clôture définitive
    ("manager", True, True),    # un manager qui clôt pour attendre son enfant actif
    ("manager", False, False),  # un manager dont les enfants ont tous fini
])
def test_la_cloture_dit_si_l_agent_attend_encore_ses_enfants(client, profil, enfant_vivant, attend):
    """La session porte, à la clôture, ce que le réveil lira : l'agent attend-il ses enfants ?"""
    from bouzecode.web_v2.tests import test_enfants_vus_par_le_parent as parent_vu
    from tests.e2e_harness import bouzecode
    from tests.fake_llm import MockLLM

    parent_vu.ecrire_agent(parent_vu.RACINE, vivant=True, ipc="running")
    parent_vu._enfant(vivant=enfant_vivant)
    config = parent_vu._config(client, **({"_task_classification_result": profil} if profil else {}))

    result = bouzecode(["Livre."], mock_llm=MockLLM([parent_vu._final("f1"), "fin"]),
                       config_overrides=config)

    assert result.state.final_answer == "Vue Tinder livrée."
    assert result.state.cloture_en_attente_des_enfants is attend
