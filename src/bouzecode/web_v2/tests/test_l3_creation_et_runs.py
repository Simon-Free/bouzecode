# [desc] Lot L3 — création d'un ticket (validation stricte, isolation jamais basculée, Idempotency-Key), PATCH en created, journal, runs (202, 409 deja_actif concurrent, isolation du ticket conservée). [/desc]
"""Critères §10 n° 4 et 5, via le vrai client Flask, le vrai store et du vrai git. Seul le spawn
du process d'agent est remplacé par l'écriture de sa fiche (`aides_l3.spawn_factice`)."""
from __future__ import annotations

import os
import threading

import pytest

from bouzecode.web_v2.services.work import tickets

from aides_l3 import attendre_etat, attendre_les_fils, spawn_factice
from aides_tickets import fiche_agent
from delivery_repo import SLUG, client, develop_repo, project  # noqa: F401 — fixtures

URL = f"/api/projects/{SLUG}/tickets"


def _creer(client, **corps):
    return client.post(URL, json={"title": "Corrige", "prompt": "corrige le calcul", **corps})


def test_isolation_inconnue_400_et_rien_n_est_cree(client, project):
    reponse = _creer(client, isolation="bidon")
    assert reponse.status_code == 400
    assert reponse.get_json()["error"]["code"] == "isolation_inconnue"
    assert tickets.list_tickets(SLUG, include_archived=True) == []


def test_un_manager_doit_choisir_son_isolation(client, project):
    reponse = _creer(client, parent={"agent_id": "mgr123", "ticket_id": "t0"}, launch=False)
    assert reponse.status_code == 400
    assert reponse.get_json()["error"]["code"] == "isolation_requise"


@pytest.mark.parametrize("corps, code", [
    ({"title": ""}, "champ_requis"), ({"title": "x" * 201}, "titre_trop_long"),
    ({"prompt": "p" * 200_001}, "prompt_trop_long"), ({"profile": "inexistant"}, "profil_inconnu"),
    ({"model": "modele-inconnu"}, "modele_inconnu")])
def test_validation_stricte(client, project, corps, code):
    reponse = _creer(client, launch=False, **corps)
    assert reponse.status_code == 400 and reponse.get_json()["error"]["code"] == code


def test_defaut_worktree_pour_l_ui_humaine_et_201(client, project):
    reponse = _creer(client, launch=False)
    assert reponse.status_code == 201
    corps = reponse.get_json()
    assert corps["ticket"]["isolation"] == "worktree" and corps["ticket"]["state"] == "created"


def test_un_shared_en_collision_donne_409_et_ne_bascule_jamais(client, project):
    fiche_agent("ecrivain1", cwd=str(project), pid=os.getpid(), ipc={"status": "running"})
    reponse = _creer(client, isolation="shared")
    assert reponse.status_code == 409
    erreur = reponse.get_json()["error"]
    assert erreur["code"] == "collision_isolation" and erreur["details"]["agents"] == ["ecrivain1"]
    assert tickets.list_tickets(SLUG) == []


def test_idempotency_key_rend_le_meme_ticket(client, project):
    en_tete = {"Idempotency-Key": "cle-1"}
    premier = client.post(URL, json={"title": "A", "prompt": "a", "launch": False}, headers=en_tete)
    second = client.post(URL, json={"title": "A", "prompt": "a", "launch": False}, headers=en_tete)
    assert premier.get_json()["ticket_id"] == second.get_json()["ticket_id"]
    assert second.get_json()["rejoue"] is True and len(tickets.list_tickets(SLUG)) == 1


def test_patch_seulement_en_created(client, project, monkeypatch):
    spawn_factice(monkeypatch)
    ticket_id = _creer(client, launch=False).get_json()["ticket_id"]
    assert client.patch(f"{URL}/{ticket_id}", json={"title": "Nouveau"}).status_code == 200
    assert tickets.get_ticket(SLUG, ticket_id)["title"] == "Nouveau"
    client.post(f"{URL}/{ticket_id}/runs", json={"defer": False})
    refus = client.patch(f"{URL}/{ticket_id}", json={"title": "Trop tard"})
    assert refus.status_code == 409 and refus.get_json()["error"]["code"] == "transition_refusee"


def test_le_journal_recoit_une_note_sans_parler_a_l_agent(client, project):
    ticket_id = _creer(client, launch=False).get_json()["ticket_id"]
    assert client.post(f"{URL}/{ticket_id}/events", json={"kind": "comment",
                                                          "text": "à revoir"}).status_code == 201
    kinds = [e["kind"] for e in client.get(f"{URL}/{ticket_id}/events").get_json()["events"]]
    assert kinds == ["created", "comment"]


def test_creation_lancee_en_fond_amene_le_ticket_a_running(client, project, monkeypatch):
    lancements = spawn_factice(monkeypatch)
    reponse = _creer(client, isolation="shared", profile="")
    assert reponse.status_code == 201 and reponse.get_json()["state"] == "provisioning"
    attendre_les_fils("lancement-", "sweep-warm-pool")
    ticket = attendre_etat(SLUG, reponse.get_json()["ticket_id"], "running")
    assert ticket["state"] == "running" and lancements[0]["cwd"] == str(project)


def test_deux_lancements_concurrents_un_202_un_409(client, project, monkeypatch):
    spawn_factice(monkeypatch)
    ticket_id = _creer(client, launch=False, isolation="shared").get_json()["ticket_id"]
    statuts, depart = [], threading.Barrier(2)

    def _lancer():
        propre = client.application.test_client()  # un client par fil (requêtes concurrentes)
        depart.wait()
        statuts.append(propre.post(f"{URL}/{ticket_id}/runs", json={}).status_code)
    fils = [threading.Thread(target=_lancer) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    assert sorted(statuts) == [202, 409]
    attendre_les_fils("relance-", "sweep-warm-pool")
    assert attendre_etat(SLUG, ticket_id, "running")["state"] == "running"  # le fil a fini


def test_relancer_conserve_l_isolation_du_ticket(client, project, monkeypatch):
    lancements = spawn_factice(monkeypatch)
    ticket_id = _creer(client, launch=False, isolation="worktree").get_json()["ticket_id"]
    reponse = client.post(f"{URL}/{ticket_id}/runs", json={"isolation": "shared", "defer": False})
    assert reponse.status_code == 202, reponse.get_json()
    assert reponse.get_json()["run"]["isolation"] == "worktree"
    assert lancements[0]["cwd"] != str(project)  # un worktree, pas le dépôt principal
    assert tickets.get_ticket(SLUG, ticket_id)["isolation"] == "worktree"
