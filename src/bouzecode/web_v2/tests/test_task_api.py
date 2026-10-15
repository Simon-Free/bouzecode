"""Le Bureau vu du navigateur : on tape dans la barre, on relit sa liste, on suit une tâche.

Tout passe par les VRAIES routes HTTP et la vraie base SQLite (isolée par la fixture autouse
`_isolate_production_state` du conftest, qui redirige TICKETS_DIR et BUREAU_DIR vers tmp_path).
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import tasks, tickets


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _created(client, **body):
    #  G1 (§4 de la spec) : une tâche exige désormais un dépôt ET un pourquoi. Les deux sont
    #  posés AVANT `**body` pour qu'un test puisse encore les retirer et vérifier le refus.
    response = client.post("/api/tasks", json={"title": "sans titre",
                                               "project_slug": "demo_ingestion",
                                               "intent": "pourquoi de test", **body})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["task"]


def test_capture_puis_liste(client):
    task = _created(client, title="migrer l'ingestion demo_table")
    assert task["state"] == "a_faire"
    listed = client.get("/api/tasks").get_json()["tasks"]
    assert [item["id"] for item in listed] == [task["id"]]
    assert listed[0]["title"] == "migrer l'ingestion demo_table"


def test_titre_vide_ou_owner_inconnu_refuses(client):
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 400
    assert client.post("/api/tasks", json={"title": "x", "owner": "chef"}).status_code == 400


def test_patch_next_step_et_garde_sur_state(client):
    agent_task = _created(client, title="tâche d'agent")
    patched = client.patch(f"/api/tasks/{agent_task['id']}", json={"next_step": "relancer"})
    assert patched.status_code == 200
    assert patched.get_json()["task"]["next_step"] == "relancer"
    # L'état d'une tâche d'agent est DÉRIVÉ : l'écrire à la main est refusé.
    refused = client.patch(f"/api/tasks/{agent_task['id']}", json={"state": "fait"})
    assert refused.status_code == 400

    mine = _created(client, title="faire valider la dérogation", owner="moi")
    accepted = client.patch(f"/api/tasks/{mine['id']}", json={"state": "en_cours"})
    assert accepted.status_code == 200
    assert accepted.get_json()["task"]["state"] == "en_cours"


def test_patch_inconnue_est_404(client):
    assert client.patch("/api/tasks/deadbeef", json={"next_step": "x"}).status_code == 404


def test_link_puis_board_derive_l_etat(client):
    ticket = tickets.create_ticket("demo_ingestion", "migrer demo_table", "prompt")
    task = _created(client, title="migrer l'ingestion demo_table")
    tasks.link_ticket(task["id"], "demo_ingestion", ticket["id"], role="work")

    # `?closed=1` : la vue PAR DÉFAUT du board est filtrée sur le vivant depuis `d5fc483b`
    # (`_board_live.keep_live`) et écarte les tâches d'agent en `a_faire` — or c'est exactement
    # l'état dérivé qu'on vérifie ici. On lit donc le board non filtré.
    board = client.get("/api/board?closed=1").get_json()
    assert board["decisions"] == [] and board["counts"]["decisions"] == 0
    entry = next(item for item in board["tasks"] if item["id"] == task["id"])
    assert [one["id"] for one in entry["tickets"]] == [ticket["id"]]
    # Ticket neuf, aucun run : `derive_status` dit « à faire », donc la tâche est `a_faire`.
    assert entry["state"] == "a_faire"
    assert entry["proposed_done"] is False


#  L'import de bureau.md (GET/POST /api/bureau/pending|import) a été RETIRÉ (§10.4) :
#  la capture v2 crée une micro-tâche en brouillon, il n'y a plus deux portes d'entrée.
#  Le service bureau_file, lui, garde ses tests dans test_bureau_file.py.
