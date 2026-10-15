"""Le board n'est pas un instantané du dernier démarrage : il suit les tickets en continu.

Tout passe par les VRAIES routes HTTP, la vraie base SQLite et le VRAI watchdog `wake.tick()`
(isolés par la fixture autouse `_isolate_production_state` du conftest). Le poller n'est pas
armé dans les tests (`BOUZECODE_WAKE_POLLER=0`) : on appelle `tick()` à la main, ce qui est
exactement la preuve cherchée — aucun redémarrage du serveur n'intervient entre la création du
ticket et son apparition sur le board.
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import tasks as tasks_service
from bouzecode.web_v2.services.work import tickets, wake

SLUG = "demo_ingestion"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _board(client, include_closed: bool = False) -> dict:
    """Le board, vue par défaut ou vue COMPLÈTE (`?closed=1`).

    La vue par défaut est filtrée sur le VIVANT depuis `d5fc483b` (`_board_live.keep_live`) : une
    tâche d'agent en `a_faire` — un ticket que personne n'a encore lancé — n'y figure PAS. Pour
    prouver le RATTRAPAGE (la tâche existe et porte son ticket), on lit donc le chemin non filtré
    `?closed=1`, qui rend `build_board(include_closed=True)` tel quel. La vue par défaut reste
    utilisée là où c'est justement son contenu qu'on vérifie (pas de tâche fantôme)."""
    url = "/api/board?closed=1" if include_closed else "/api/board"
    response = client.get(url)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _tasks_of_ticket(board: dict, ticket_id: str) -> list[dict]:
    return [
        task for task in board["tasks"]
        if any(one["id"] == ticket_id for one in task["tickets"])
    ]


def test_un_ticket_cree_apres_le_boot_arrive_sur_le_board_sans_redemarrage(client):
    # `create_app` a déjà tourné (fixture) : la migration de boot est passée AVANT ce ticket.
    ticket = tickets.create_ticket(SLUG, "intégration Teams", "prompt")

    assert _tasks_of_ticket(_board(client, include_closed=True), ticket["id"]) == []

    wake.tick()  # un simple cycle du watchdog, sans redémarrer quoi que ce soit

    tasks = _tasks_of_ticket(_board(client, include_closed=True), ticket["id"])
    assert len(tasks) == 1, "le ticket créé après le boot doit devenir une tâche"
    assert tasks[0]["title"] == "intégration Teams"
    assert tasks[0]["owner"] == "agent"


def test_le_rattrapage_repete_ne_double_jamais_une_tache(client):
    ticket = tickets.create_ticket(SLUG, "migrer demo_table", "prompt")
    for _ in range(3):
        wake.tick()

    tasks = _tasks_of_ticket(_board(client, include_closed=True), ticket["id"])
    assert len(tasks) == 1
    assert [one["id"] for one in tasks[0]["tickets"]] == [ticket["id"]]


def test_un_ticket_archive_ne_laisse_pas_de_tache_fantome(client):
    ticket = tickets.create_ticket(SLUG, "vieux chantier", "prompt")
    wake.tick()
    born = _tasks_of_ticket(_board(client, include_closed=True), ticket["id"])
    assert len(born) == 1
    # On retient l'ID de la tâche AVANT l'archivage : le board écarte les tickets archivés, donc
    # après coup la tâche n'est plus jointe à ce ticket_id — seul l'ID de tâche reste comparable.
    task_id = born[0]["id"]

    tickets.archive_ticket(SLUG, ticket["id"])  # lot L2 : jamais un instantané périmé
    wake.tick()

    ouvert = _board(client)["tasks"]
    assert not any(task["id"] == task_id for task in ouvert), "tâche fantôme sur le board"

    # Clôturée, PAS effacée : elle quitte le board mais reste en base, avec son motif. On lit la
    # base directement, car `GET /api/board` ne rend que les tâches ouvertes (aucune query).
    clos = tasks_service.get_task(task_id)
    assert clos, "la tâche doit être clôturée, pas supprimée"
    assert clos["state"] == "abandonnee"
    assert clos["outcome"] == "ticket disparu"
    assert clos["closed_at"]


def test_une_tache_saisie_a_la_main_survit_au_rattrapage(client):
    created = client.post("/api/tasks", json={"title": "appeler le chef", "owner": "moi",
                                              "project_slug": "bouzecode",
                                              "intent": "arbitrage humain, aucun agent"})
    assert created.status_code == 201, created.get_data(as_text=True)
    task_id = created.get_json()["task"]["id"]

    wake.tick()

    board = _board(client)
    assert any(task["id"] == task_id for task in board["tasks"]), (
        "une tâche sans ticket est une saisie humaine : le rattrapage ne doit pas la clôturer"
    )


def test_counts_ne_porte_plus_qu_une_seule_cle_bloquee(client):
    counts = _board(client)["counts"]
    assert "bloquee" in counts
    assert "bloquees" not in counts, "clé en doublon : la convention des autres clés est le singulier"
