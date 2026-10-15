# [desc] Lot L3, critère §10 n° 1 : appeler 10 fois chaque GET de l'API cible ne change ni le store (empreinte de tickets.db), ni les branches git, ni les process vivants. [/desc]
"""Lecture pure : liste (filtres, pagination), fiche, journal, runs, diff, occupation, agents,
fiche d'agent, enfants. Vrai store, vrai git (un ticket isolé livré), aucun mock."""
from __future__ import annotations

import hashlib
import os

import psutil

from bouzecode.web_v2.services.work import _persistence, tickets

from aides_l3 import ticket_isole
from aides_tickets import fiche_agent
from delivery_repo import SLUG, client, develop_repo, git_out, project  # noqa: F401 — fixtures

URL = f"/api/projects/{SLUG}/tickets"


def _empreinte_du_store() -> str:
    with _persistence._connect() as conn:
        lignes = [conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                  for table in ("tickets", "runs", "ticket_events", "idempotence")]
    return hashlib.sha256(repr(lignes).encode("utf-8")).hexdigest()


def _process_vivants() -> set[int]:
    return {p.pid for p in psutil.process_iter()}


def test_dix_lectures_de_chaque_get_ne_changent_rien(client, project):
    ticket = ticket_isole(project, "lu", {"lu.py": "x\n"})
    manager = tickets.create_ticket(SLUG, "manager", "orchestre")
    tickets.poser(SLUG, manager, parent="")
    tickets.poser(SLUG, ticket, parent="agmanager01")
    fiche_agent("agmanager01", slug=SLUG, ticket_id=manager["id"])
    lectures = [f"{URL}", f"{URL}?state=delivered,created&limit=1", f"{URL}?archived=all",
                f"{URL}/{ticket['id']}", f"{URL}/{ticket['id']}/events",
                f"{URL}/{ticket['id']}/runs", f"{URL}/{ticket['id']}/diff",
                f"/api/projects/{SLUG}/occupation", "/api/agents", "/api/agents?state=stopped",
                "/api/agents/agmanager01", "/api/agents/agmanager01/children"]
    for url in lectures:  # une première lecture : les caches de process se remplissent
        assert client.get(url).status_code == 200, url
    store, branches = _empreinte_du_store(), git_out(project, "for-each-ref")
    process = _process_vivants()

    for _ in range(10):
        for url in lectures:
            assert client.get(url).status_code == 200, url

    assert _empreinte_du_store() == store
    assert git_out(project, "for-each-ref") == branches
    disparus = process - _process_vivants()
    assert os.getpid() not in disparus and not (disparus & {p.pid for p in psutil.Process().children()})


def test_la_liste_se_pagine_par_curseur_et_se_filtre(client, project):
    ids = [tickets.create_ticket(SLUG, f"T{i}", "p")["id"] for i in range(5)]
    page1 = client.get(f"{URL}?limit=2").get_json()
    page2 = client.get(f"{URL}?limit=2&cursor={page1['next_cursor']}").get_json()
    page3 = client.get(f"{URL}?limit=2&cursor={page2['next_cursor']}").get_json()
    vus = [t["id"] for page in (page1, page2, page3) for t in page["tickets"]]
    assert sorted(vus) == sorted(ids) and page3["next_cursor"] is None and page1["total"] == 5
    assert client.get(f"{URL}?state=delivered").get_json()["tickets"] == []
    assert client.get(f"{URL}?state=bidon").status_code == 400


def test_les_runs_legacy_restent_visibles_en_lecture_seule(client, project):
    """Limite L2 (c) : l'occurrence d'un agent déjà propriété d'un autre ticket reste sous
    `legacy.runs` ; la fiche et …/runs la servent à part, marquée lecture seule."""
    ticket = tickets.create_ticket(SLUG, "hérité", "p")
    tickets.poser(SLUG, ticket, legacy={"runs": [{"agent_id": "agpartage01", "kind": "work"}]})

    fiche = client.get(f"{URL}/{ticket['id']}").get_json()
    runs = client.get(f"{URL}/{ticket['id']}/runs").get_json()

    assert fiche["runs"] == [] and runs["runs"] == []
    assert fiche["legacy_runs"] == runs["legacy_runs"] == [
        {"agent_id": "agpartage01", "kind": "work", "legacy": True, "lecture_seule": True}]


def test_un_meme_agent_ne_peut_pas_etre_rattache_a_deux_tickets(client, project):
    from bouzecode.web_v2.services.work.fsm.stockage import RunDejaRattache
    premier = tickets.create_ticket(SLUG, "A", "p")
    second = tickets.create_ticket(SLUG, "B", "p")
    tickets.set_launching(SLUG, premier)
    tickets.add_run(SLUG, premier, "agunique001", "work", "")
    tickets.set_launching(SLUG, second)

    try:
        tickets.add_run(SLUG, second, "agunique001", "work", "")
    except RunDejaRattache as refus:
        assert premier["id"] in str(refus)
    else:
        raise AssertionError("un même agent a été rattaché à deux tickets")
    assert [r["agent_id"] for r in tickets.get_ticket(SLUG, second["id"])["runs"]] == []
