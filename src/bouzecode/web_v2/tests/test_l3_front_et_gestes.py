# [desc] Lot L3 — le front n'appelle plus aucune route dépréciée (test statique sur static/js) ; gestes sur l'agent d'un ticket : messages (200 delivered / 202 queued / 409 pas_d_agent), answer, stop (idempotent). [/desc]
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime.runner import agent_processus, agent_reprise
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import file_messages, tickets
from bouzecode.web_v2.services.work.fsm import etats

from aides_tickets import en_cours, fiche_agent
from delivery_repo import SLUG, client, develop_repo, project  # noqa: F401 — fixtures

STATIC_JS = Path(__file__).resolve().parents[1] / "static" / "js"
DEPRECIEES = [r"/api/tickets/", r"/api/dispatch", r"/api/agent/message", r"/continue\b",
              r"/kill\b", r"/interrupt\b(?!ions)", r"/enfants\b", r"/relaunch\b",
              r"/api/agents?state=awaiting_input", r"/api/agents?state=unreachable",
              r"/api/agents?state=interrupted", r"/api/agents?state=interrupted(?!/dismiss)",
              r"/api/projects/[^/\"'`]+/agents"]


def test_le_front_n_appelle_plus_aucune_route_depreciee():
    fautes = []
    for chemin in STATIC_JS.rglob("*.js"):
        texte = chemin.read_text(encoding="utf-8")
        for motif in DEPRECIEES:
            for trouve in re.finditer(motif, texte):
                ligne = texte.count("\n", 0, trouve.start()) + 1
                fautes.append(f"{chemin.relative_to(STATIC_JS)}:{ligne} {trouve.group(0)}")
    assert fautes == [], "routes dépréciées encore appelées par le front :\n" + "\n".join(fautes)


URL = f"/api/projects/{SLUG}/tickets"


def test_un_message_a_un_agent_au_repos_est_livre(client, project, monkeypatch):
    ticket = en_cours(SLUG, "agrepos0001")
    fiche_agent("agrepos0001", slug=SLUG, ticket_id=ticket["id"], cwd=str(project))
    monkeypatch.setattr(store, "agent_status", lambda agent: {"state": "finished"})
    monkeypatch.setattr(agent_processus, "session_process_running", lambda path: False)
    relances = []
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, texte: relances.append(texte) or agent)

    reponse = client.post(f"{URL}/{ticket['id']}/messages", json={"text": "reprends"})

    assert reponse.status_code == 200 and reponse.get_json()["delivered"] is True
    assert relances == ["reprends"]
    notes = tickets.get_ticket(SLUG, ticket["id"])["comments"]
    assert (notes[-1]["text"], notes[-1]["sent"]) == ("reprends", True)


def test_un_message_pendant_un_tour_est_mis_en_file(client, project):
    ticket = en_cours(SLUG, "agtour00001")
    fiche_agent("agtour00001", slug=SLUG, ticket_id=ticket["id"], pid=os.getpid(),
                ipc={"status": "running"})

    reponse = client.post(f"{URL}/{ticket['id']}/messages", json={"text": "et aussi ça"})

    assert reponse.status_code == 202, reponse.get_json()
    corps = reponse.get_json()
    assert corps["queued"] is True and corps["queue_id"] and corps["position"] == 1
    assert [i["text"] for i in file_messages.lister("agtour00001")] == ["et aussi ça"]


def test_sans_run_le_message_est_refuse_et_garde_au_journal(client, project):
    ticket = tickets.create_ticket(SLUG, "jamais lancé", "p")

    reponse = client.post(f"{URL}/{ticket['id']}/messages", json={"text": "allô"})

    assert reponse.status_code == 409
    erreur = reponse.get_json()["error"]
    assert erreur["code"] == "pas_d_agent" and erreur["details"]["commentaire_conserve"] is True
    notes = tickets.get_ticket(SLUG, ticket["id"])["comments"]
    assert (notes[-1]["text"], notes[-1]["sent"]) == ("allô", False)


def test_answer_sans_question_en_attente_est_un_409(client, project):
    ticket = en_cours(SLUG, "agrepond001")
    reponse = client.post(f"{URL}/{ticket['id']}/answer", json={"text": "oui"})
    assert reponse.status_code == 409 and reponse.get_json()["error"]["code"] == "pas_de_question"


def test_stop_sur_un_ticket_sans_agent_vivant_est_idempotent(client, project):
    ticket = tickets.create_ticket(SLUG, "rien à arrêter", "p")
    for _ in range(2):
        reponse = client.post(f"{URL}/{ticket['id']}/stop")
        assert reponse.status_code == 202 and reponse.get_json()["state"] == etats.CREATED


@pytest.mark.parametrize("mode", ["bidon"])
def test_un_mode_de_message_inconnu_est_un_400(client, project, mode):
    ticket = en_cours(SLUG, "agmode00001")
    reponse = client.post(f"{URL}/{ticket['id']}/messages", json={"text": "x", "mode": mode})
    assert reponse.status_code == 400 and reponse.get_json()["error"]["code"] == "mode_inconnu"
