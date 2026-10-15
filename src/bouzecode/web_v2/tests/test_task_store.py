"""Les tâches vivent dans la base des tickets EXISTANTE, et la migration de boot est rejouable.

Aucun mock : vraie base SQLite, vrais tickets, dans le TICKETS_DIR temporaire posé par la fixture
autouse du conftest.
"""

import pytest

from bouzecode.web_v2.services.work import _persistence, task_migration, tickets
from bouzecode.web_v2.services.work import tasks as tasks_service


def _seed(slug: str, title: str, agent_id: str = "", parent: str = "",
          archived: bool = False, state: str = "done") -> dict:
    ticket = tickets.create_ticket(slug, title, "peu importe")
    if agent_id:
        ticket["runs"] = [{"agent_id": agent_id, "kind": "work", "state": state}]
    if parent:
        ticket["parent"] = parent
    if archived:
        ticket["archived"] = True
    tickets.update_ticket(slug, ticket)
    return ticket


def test_les_tables_sont_dans_la_base_des_tickets_et_pas_dans_un_nouveau_fichier():
    tasks_service.create_task("écrire la spec")
    db_path = _persistence._db_path()
    assert db_path.exists()
    with _persistence._connect() as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "task_tickets", "task_events"} <= names
    autres = [p.name for p in db_path.parent.glob("*.db") if p.name != db_path.name]
    assert autres == []


def test_cycle_de_vie_dune_tache():
    task = tasks_service.create_task("migrer l'ingestion", intent="détail", project_slug="demo")
    assert task["state"] == "a_faire"
    assert task["policy"] == "observer"
    assert [t["id"] for t in tasks_service.list_tasks()] == [task["id"]]

    tasks_service.update_task(task["id"], next_step="attendre la livraison")
    assert tasks_service.get_task(task["id"])["next_step"] == "attendre la livraison"

    tasks_service.link_ticket(task["id"], "demo", "a91f")
    assert [l["ticket_id"] for l in tasks_service.links_of(task["id"])] == ["a91f"]
    # Lier deux fois le même ticket ne le duplique pas (clé primaire composite).
    tasks_service.link_ticket(task["id"], "demo", "a91f")
    assert len(tasks_service.links_of(task["id"])) == 1

    tasks_service.add_event(task["id"], actor="moi", kind="note", label="relancé à la main")
    labels = [e["label"] for e in tasks_service.events_of(task["id"])]
    assert "tâche créée" in labels and "relancé à la main" in labels

    tasks_service.close_task(task["id"], "fait")
    assert tasks_service.list_tasks() == []
    closed = tasks_service.get_task(task["id"])
    assert closed["outcome"] == "fait" and closed["closed_at"]
    assert [t["id"] for t in tasks_service.list_tasks(include_closed=True)] == [task["id"]]


def test_update_task_refuse_un_champ_hors_liste_blanche():
    task = tasks_service.create_task("ne pas tout laisser écrire")
    with pytest.raises(ValueError):
        tasks_service.update_task(task["id"], closed_at="2026-01-01T00:00:00")


def test_la_migration_enveloppe_les_tickets_et_est_idempotente():
    # Racines EN COURS d'exécution : un ticket déjà terminé est volontairement
    # écarté par la migration (_is_finished — enrôler un « fait » ne sert à rien),
    # donc le test doit porter des tickets vivants pour être enveloppés.
    _seed("demo", "racine A", agent_id="ag-a", state="running")
    _seed("demo", "enfant de A", parent="ag-a")
    _seed("demo", "racine B", agent_id="ag-b", state="running")
    _seed("demo", "vieux truc archivé", agent_id="ag-z", archived=True)

    created = task_migration.migrate_tickets_into_tasks()
    assert created == 2  # deux racines non archivées, l'enfant rejoint la tâche de son parent

    titles = sorted(t["title"] for t in tasks_service.list_tasks())
    assert titles == ["racine A", "racine B"]
    assert all(t["policy"] == "observer" for t in tasks_service.list_tasks())

    par_titre = {t["title"]: t["id"] for t in tasks_service.list_tasks()}
    liens_de_a = {l["ticket_id"] for l in tasks_service.links_of(par_titre["racine A"])}
    assert len(liens_de_a) == 2  # la racine ET son enfant sont sur la même tâche

    # Aucune tâche pour un ticket archivé.
    archives = [t for t in tasks_service.list_tasks(include_closed=True)
                if t["title"] == "vieux truc archivé"]
    assert archives == []

    liens_avant = len(tasks_service.all_links())
    assert task_migration.migrate_tickets_into_tasks() == 0
    assert len(tasks_service.list_tasks()) == 2
    assert len(tasks_service.all_links()) == liens_avant
