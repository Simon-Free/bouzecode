"""Le board ne tombe JAMAIS à cause de la date d'une carte.

Régression de production (commit 4db5c3eb) : `GET /api/board` rendait 500 avec
`TypeError: can't subtract offset-naive and offset-aware datetimes`, parce que `_waiting_s`
comparait `datetime.now()` (local NAÏF) à un `asked_at` de question d'agent en UTC AWARE.
Le board marchait tant qu'il n'y avait que des livraisons (dates naïves) et tombait à la
première ingestion de questions d'agents — c'est-à-dire quand L2 faisait enfin son travail.

Tout se lit sur `GET /api/board`, comme l'écran. Ces tests vérifient une VALEUR, pas seulement
l'absence d'exception : une normalisation qui
« suppose UTC » sur une date naïve ne lève pas non plus, mais fabrique une attente fantôme de
7 200 s (le piège déjà payé sur ce parc avec `created_at` local / `started_at` UTC).
"""
from datetime import datetime, timedelta, timezone

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import decisions as decisions_store

TOLERANCE_S = 3  # le temps que le test s'exécute


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _naive_local(age_s: int) -> str:
    """L'ANCIENNE forme, encore présente en base de production : ISO local SANS fuseau.

    `decision_ingest._now()` écrit désormais un décalage explicite, mais les cartes déjà
    stockées sont naïves : le calcul doit continuer de les lire comme des dates LOCALES."""
    return (datetime.now() - timedelta(seconds=age_s)).isoformat(timespec="seconds")


def _aware_utc(age_s: int) -> str:
    """Ce que produit `awaiting.agents_awaiting_answer()` : UTC avec fuseau (`...+00:00`)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()


def _aware_offset(age_s: int, hours: int = 5) -> str:
    """Le même instant, écrit dans un fuseau à décalage non nul."""
    quand = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return quand.astimezone(timezone(timedelta(hours=hours))).isoformat()


# --- le board complet, tel que l'écran le lit --------------------------------------------------

def _carte(ticket_id: str, asked_at: str) -> None:
    decisions_store.upsert(
        source="agent_question", situation="question_agent",
        question=f"question {ticket_id}", asked_at=asked_at,
        project_slug="demo_ingestion", ticket_id=ticket_id, agent_id=ticket_id,
        urgency=0, bucket="",
    )


def _cartes_du_board(client) -> dict[str, dict]:
    response = client.get("/api/board")
    assert response.status_code == 200, response.get_data(as_text=True)
    return {carte["ticket_id"]: carte for carte in response.get_json()["decisions"]}


def test_le_board_repond_200_avec_les_trois_sortes_de_dates_melangees(client):
    _carte("T-naif", _naive_local(60))
    _carte("T-utc", _aware_utc(3600))
    _carte("T-decale", _aware_offset(120))

    cartes = _cartes_du_board(client)

    assert abs(cartes["T-naif"]["waiting_s"] - 60) <= TOLERANCE_S
    assert abs(cartes["T-utc"]["waiting_s"] - 3600) <= TOLERANCE_S
    assert abs(cartes["T-decale"]["waiting_s"] - 120) <= TOLERANCE_S


def test_une_carte_a_la_date_cassee_ne_fait_pas_tomber_le_board_entier(client):
    _carte("T-sain", _aware_utc(600))
    _carte("T-casse", _aware_utc(600))
    _carte("T-vide", _aware_utc(600))
    # `upsert` refuse d'écrire un `asked_at` vide (`asked_at or _now()`) : on abîme la base
    # directement, comme le ferait une écriture d'une version antérieure du code.
    with decisions_store._tx() as conn:
        conn.execute("UPDATE decisions SET asked_at = 'pas-une-date' WHERE ticket_id = 'T-casse'")
        conn.execute("UPDATE decisions SET asked_at = '' WHERE ticket_id = 'T-vide'")

    cartes = _cartes_du_board(client)

    assert abs(cartes["T-sain"]["waiting_s"] - 600) <= TOLERANCE_S
    assert cartes["T-casse"]["waiting_s"] is None, "la carte sort, avec une ancienneté inconnue"
    assert cartes["T-vide"]["waiting_s"] is None
    assert len(cartes) >= 3, "aucune carte ne doit disparaître à cause de sa date"


def test_une_question_qui_attend_depuis_27_jours_est_comptee_en_jours(client):
    """Le cas réel de production : des questions d'agents en attente depuis ~27 jours."""
    attendu = 27 * 86400
    _carte("T-vieux", _aware_utc(attendu))
    assert abs(_cartes_du_board(client)["T-vieux"]["waiting_s"] - attendu) <= TOLERANCE_S


@pytest.mark.parametrize("casse", ["pas-une-date", "2026-13-45T99:99:99"])
def test_une_date_inexploitable_donne_une_anciennete_inconnue_pas_zero(client, casse):
    """Inconnue, PAS zéro : « attend depuis 0 s » mettrait la carte cassée en tête du tri."""
    _carte("T-illisible", _aware_utc(600))
    with decisions_store._tx() as conn:
        conn.execute("UPDATE decisions SET asked_at = ? WHERE ticket_id = 'T-illisible'",
                     (casse,))
    assert _cartes_du_board(client)["T-illisible"]["waiting_s"] is None
