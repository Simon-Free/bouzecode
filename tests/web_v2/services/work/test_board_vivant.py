"""Le board du Bureau ne porte que le VIVANT ; les archives restent consultables.

Point d'entrée testé : l'API HTTP réelle (`GET /api/board`, `GET /api/board?closed=1`,
`GET /api/tasks?closed=1`) et la réconciliation rejouée en continu par le watchdog.
"""
import uuid

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import constats, task_migration, tasks, ticket_fsm, tickets
from bouzecode.web_v2.services.work.fsm import etats


def _client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _ticket(titre: str, etat: str = etats.CREATED) -> dict:
    """Un ticket amené dans `etat` par la machine à états (en cours, livré, arrêté, clos)."""
    ticket = tickets.create_ticket("demo", titre, "prompt")
    if etat == etats.CREATED:
        return ticket
    agent = uuid.uuid4().hex[:12]
    tickets.set_launching("demo", ticket)
    tickets.add_run("demo", ticket, agent, "work", "m")
    if etat == etats.STOPPED:
        ticket_fsm.appliquer("demo", ticket["id"], etats.CRASHED)
    elif etat in (etats.DELIVERED, etats.CLOSED):
        constats.fin_de_run("demo", ticket["id"], agent, "final_answer")
    if etat == etats.CLOSED:
        ticket_fsm.appliquer("demo", ticket["id"], etats.CLOSE)
    return tickets.get_ticket("demo", ticket["id"])


def _finir(ticket: dict) -> None:
    """Le travail est fait et la décision prise : le ticket est clos."""
    frais = tickets.get_ticket("demo", ticket["id"])
    if frais["state"] == etats.CREATED:
        frais = _ticket_relance(frais)
    if frais["state"] == etats.RUNNING:
        constats.fin_de_run("demo", frais["id"], frais["runs"][0]["agent_id"], "final_answer")
    ticket_fsm.appliquer("demo", frais["id"], etats.CLOSE)


def _ticket_relance(ticket: dict) -> dict:
    tickets.set_launching("demo", ticket)
    tickets.add_run("demo", ticket, uuid.uuid4().hex[:12], "work", "m")
    return tickets.get_ticket("demo", ticket["id"])


# --- 3. la migration cesse d'enrôler les tickets déjà terminés ---------------

def test_migration_ne_cree_pas_de_tache_pour_un_ticket_deja_termine():
    _ticket("deja fini", etats.CLOSED)
    _ticket("en cours", etats.RUNNING)

    cree = task_migration.migrate_tickets_into_tasks()

    assert cree == 1
    titres = [task["title"] for task in tasks.list_tasks(include_closed=True)]
    assert not any("deja fini" in titre for titre in titres), titres


def test_une_tache_existante_qui_se_termine_reste_mais_close():
    ticket = _ticket("boulot", etats.RUNNING)
    assert task_migration.reconcile_tasks_with_tickets() == {"created": 1, "closed": 0}
    task_id = tasks.list_tasks()[0]["id"]

    _finir(ticket)
    premier = task_migration.reconcile_tasks_with_tickets()

    assert premier == {"created": 0, "closed": 1}
    archives = tasks.list_tasks(include_closed=True)
    assert [task["id"] for task in archives] == [task_id], "la tâche a été recréée ou effacée"
    assert archives[0]["closed_at"] and archives[0]["outcome"] == "fait"
    assert tasks.list_tasks() == []

    # Rejouée en continu : deuxième passage strictement neutre (idempotence).
    assert task_migration.reconcile_tasks_with_tickets() == {"created": 0, "closed": 0}
    assert [task["id"] for task in tasks.list_tasks(include_closed=True)] == [task_id]
    assert tasks.list_tasks() == []


# --- 4. rattrapage de l'existant --------------------------------------------

def test_rattrapage_des_taches_deja_en_base_les_termine_sans_rien_effacer():
    finis = [_ticket(f"fini {n}") for n in range(3)]
    for ticket in finis:
        task_migration.migrate_tickets_into_tasks()  # tâches créées avant le correctif
        _finir(ticket)
    avant = len(tasks.list_tasks(include_closed=True))
    assert avant == 3

    task_migration.reconcile_tasks_with_tickets()

    assert len(tasks.list_tasks(include_closed=True)) == avant, "des archives ont disparu"
    assert tasks.list_tasks() == []
    assert all(task["outcome"] == "fait" for task in tasks.list_tasks(include_closed=True))


# --- 1. le board ne porte que le vivant -------------------------------------

def test_le_board_ne_montre_que_le_vivant():
    _ticket("en cours", etats.RUNNING)
    _ticket("a relire", etats.DELIVERED)
    _ticket("plante", etats.STOPPED)
    _ticket("jamais lance")
    fini = _ticket("fini")
    task_migration.migrate_tickets_into_tasks()
    _finir(fini)
    tasks.create_task(title="ma tache a moi", project_slug="demo", owner="moi", policy="observer")
    task_migration.reconcile_tasks_with_tickets()

    board = _client().get("/api/board").get_json()

    titres = sorted(task["title"] for task in board["tasks"])
    assert "ma tache a moi" in titres, "une tâche saisie à la main doit rester visible"
    assert not any("fini" in titre for titre in titres), titres
    assert not any("jamais lance" in titre for titre in titres), titres
    etats_vus = {task["state"] for task in board["tasks"]}
    assert etats_vus <= {"en_cours", "bloquee", "a_relire", "a_faire"}
    assert board["counts"]["fait"] == 0
    assert board["counts"]["closes"] >= 1


# --- 2. les archives restent consultables -----------------------------------

def test_les_archives_restent_consultables_sans_etre_chargees_par_defaut():
    ticket = _ticket("boulot fini", etats.RUNNING)
    task_migration.migrate_tickets_into_tasks()
    _finir(ticket)
    task_migration.reconcile_tasks_with_tickets()
    client = _client()

    defaut = client.get("/api/board").get_json()
    archives = client.get("/api/board?closed=1").get_json()
    api_tasks = client.get("/api/tasks?closed=1").get_json()

    assert defaut["tasks"] == [], "le board par défaut ne doit rien porter de clos"
    assert defaut["counts"]["closes"] == 1, "le compteur annonce les closes sans les charger"
    assert [task["title"] for task in archives["tasks"]] == ["boulot fini"]
    assert any(task["closed_at"] for task in api_tasks["tasks"])
