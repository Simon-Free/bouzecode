"""Le Bureau dit ce qu'il reste à FAIRE : les décisions ouvertes sont sur le board.

Point d'entrée testé : l'API HTTP réelle (`GET /api/board`, `POST /api/decisions/<id>/answer`),
pas les services internes. Une carte de décision qui n'arrive pas jusqu'au JSON du board
n'existe pas pour l'utilisateur, quoi qu'en dise la table SQLite.

Aucun mock : vraie app Flask, vraie base SQLite (la fixture autouse `_isolate_production_state`
de `tests/conftest.py` redirige TICKETS_DIR vers un dossier temporaire).
"""
from datetime import datetime, timedelta

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import _board_live, decisions, task_migration, tasks, tickets
from bouzecode.web_v2.tests.aides_tickets import en_cours


def _client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _ticket(titre: str, **flags) -> dict:
    ticket = tickets.create_ticket("demo", titre, "prompt")
    if flags:
        ticket.update(flags)
        tickets.update_ticket("demo", ticket)
    return ticket


def _il_y_a(secondes: int) -> str:
    return (datetime.now() - timedelta(seconds=secondes)).isoformat(timespec="seconds")


def _carte(situation: str, *, urgency: int, il_y_a: int, task_id: str = "",
           ticket_id: str = "", question: str = "et alors ?", **extra) -> dict:
    return decisions.upsert(
        "situation", situation, question,
        asked_at=_il_y_a(il_y_a), task_id=task_id, project_slug="demo",
        ticket_id=ticket_id or situation, agent_id="", context="",
        options=extra.get("options") or [], allow_freetext=True,
        recommended=extra.get("recommended", ""), urgency=urgency, bucket="",
    )


def _tache_liee() -> tuple[str, dict]:
    """Un ticket vivant enrôlé en tâche : rend (task_id, ticket)."""
    ticket = en_cours("demo", "a1", "boulot")  # lot L2 : lancé par le vrai chemin (`running`)
    task_migration.reconcile_tasks_with_tickets()
    return tasks.list_tasks()[0]["id"], ticket


# --- 1. les décisions ouvertes sortent du board, triées ----------------------

def test_le_board_porte_les_decisions_triees_urgence_puis_anciennete():
    _carte("moins_urgent", urgency=2, il_y_a=9000)
    _carte("urgent_recent", urgency=1, il_y_a=60)
    _carte("urgent_ancien", urgency=1, il_y_a=7200)

    payload = _client().get("/api/board").get_json()

    situations = [carte["situation"] for carte in payload["decisions"]]
    assert situations == ["urgent_ancien", "urgent_recent", "moins_urgent"], situations


def test_chaque_carte_dit_depuis_combien_de_temps_elle_attend():
    _carte("livraison_a_relire", urgency=1, il_y_a=3600,
           question="intégrer les 9 commits de agent/abc ?",
           options=[{"key": "integrer", "label": "Intégrer"},
                    {"key": "abandonner", "label": "Abandonner"}],
           recommended="integrer")

    carte = _client().get("/api/board").get_json()["decisions"][0]

    assert carte["question"] == "intégrer les 9 commits de agent/abc ?"
    assert carte["urgency"] == 1
    assert carte["recommended"] == "integrer"
    assert [option["key"] for option in carte["options"]] == ["integrer", "abandonner"]
    # L'attente est un CHIFFRE : « depuis 21 jours » est le fait qui fait agir.
    assert 3500 <= carte["waiting_s"] <= 3700, carte["waiting_s"]


# --- 2. les compteurs, et le report par tâche --------------------------------

def test_les_compteurs_et_la_tache_portent_le_nombre_de_decisions_ouvertes():
    task_id, _ = _tache_liee()
    _carte("un", urgency=1, il_y_a=10, task_id=task_id)
    _carte("deux", urgency=2, il_y_a=20, task_id=task_id)
    _carte("orpheline", urgency=3, il_y_a=30)

    payload = _client().get("/api/board").get_json()

    assert payload["counts"]["decisions"] == 3
    tache = next(task for task in payload["tasks"] if task["id"] == task_id)
    assert tache["open_decisions"] == 2, payload["tasks"]


def test_le_filtre_du_vivant_ne_jette_pas_les_decisions():
    """`keep_live` réduit les tâches mais ne doit ni perdre les cartes ni remettre le compte à 0."""
    _carte("survivante", urgency=1, il_y_a=10)
    payload = _client().get("/api/board").get_json()

    filtre = _board_live.keep_live(payload)

    assert [carte["situation"] for carte in filtre["decisions"]] == ["survivante"]
    assert filtre["counts"]["decisions"] == 1


# --- 3. répondre à une décision depuis l'API --------------------------------

def test_repondre_a_une_decision_la_retire_du_board():
    carte = _carte("livraison_a_relire", urgency=1, il_y_a=600,
                   options=[{"key": "abandonner", "label": "Abandonner"}])
    client = _client()

    reponse = client.post(f"/api/decisions/{carte['id']}/answer",
                          json={"answer_key": "abandonner", "answer_text": "obsolète"})

    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    corps = reponse.get_json()
    assert corps["decision"]["answer_key"] == "abandonner"
    assert corps["decision"]["answered_at"], corps
    assert _client().get("/api/board").get_json()["decisions"] == []


def test_repondre_deux_fois_ne_recrit_pas_la_premiere_reponse():
    carte = _carte("livraison_a_relire", urgency=1, il_y_a=600)
    client = _client()
    client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_key": "integrer"})

    seconde = client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_key": "abandonner"})

    assert seconde.status_code == 409, seconde.get_data(as_text=True)
    assert decisions.get(carte["id"])["answer_key"] == "integrer"


def test_repondre_a_une_decision_inconnue_dit_404():
    reponse = _client().post("/api/decisions/9999/answer", json={"answer_key": "x"})

    assert reponse.status_code == 404, reponse.get_data(as_text=True)
