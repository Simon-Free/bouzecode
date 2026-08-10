# [desc] Le store de tickets réutilise sa connexion SQLite par thread, sans jamais servir de données périmées. [/desc]
"""Coût d'OUVERTURE du store, payé à chaque affichage du board.

Mesuré sur le store réel : ouvrir une connexion SQLite coûte 30 à 130 ms (ouverture du
`.db` + de son `-wal` de 4 Mo + `PRAGMA journal_mode=WAL`), contre 0,03 ms sur une
connexion déjà ouverte. `GET /api/projects/<slug>/tickets` en ouvrait ~101 par requête —
une par `_load`, une par `get_ticket` de `workflow.advance`, une par `update_ticket` de
`wake._stamp_liveness` — soit ~13 s de pure ouverture sur les ~25 s de la requête.

Ces tests fixent les DEUX moitiés du contrat : la connexion est réutilisée, ET la
réutilisation ne fige aucun instantané (le board sert à superviser des agents en cours,
une donnée périmée y serait pire que la lenteur).
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import tickets as tickets_svc

SLUG = "projet-du-store"


@pytest.fixture()
def opened_connections(monkeypatch) -> list[str]:
    """Compte les ouvertures PHYSIQUES de connexion, puis délègue au vrai sqlite3."""
    opened: list[str] = []
    real_connect = sqlite3.connect

    def counting_connect(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(_persistence.sqlite3, "connect", counting_connect)
    return opened


def _seed_board(count: int) -> list[dict]:
    return [tickets_svc.create_ticket(SLUG, f"ticket {index}", "fais le travail")
            for index in range(count)]


def test_a_board_sized_burst_of_reads_and_writes_opens_a_single_connection(opened_connections):
    """Le motif d'accès du board (une liste, puis une relecture et une écriture par ticket)
    n'ouvre qu'UNE connexion — avant le correctif, il en ouvrait une par appel."""
    tickets = _seed_board(20)

    for ticket in tickets_svc.list_tickets(SLUG):
        reloaded = tickets_svc.get_ticket(SLUG, ticket["id"])
        reloaded["comments"] = [{"at": "2026-07-28", "text": "vu", "sent": False}]
        tickets_svc.update_ticket(SLUG, reloaded)

    assert len(tickets) == 20
    assert len(opened_connections) == 1, (
        f"{len(opened_connections)} ouvertures pour 61 requêtes store : la connexion "
        "n'est pas réutilisée")


def test_a_write_made_by_another_thread_is_read_fresh(opened_connections):
    """Un ticket écrit par un AUTRE thread (un agent, le watchdog) est lu à jour : la
    connexion réutilisée ne sert pas l'instantané du dernier appel."""
    ticket = tickets_svc.create_ticket(SLUG, "supervisé", "surveille")
    tickets_svc.get_ticket(SLUG, ticket["id"])  # ouvre et réchauffe la connexion du thread

    def write_from_another_thread() -> None:
        tickets_svc.add_run(SLUG, dict(ticket), "agent-frais", "work", "opus")

    writer = threading.Thread(target=write_from_another_thread)
    writer.start()
    writer.join()

    reloaded = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert [run["agent_id"] for run in reloaded["runs"]] == ["agent-frais"]


def test_a_write_is_visible_to_the_next_read_on_the_same_thread():
    """Écrire puis relire sur le MÊME thread rend la valeur écrite, pas la précédente."""
    ticket = tickets_svc.create_ticket(SLUG, "à finir", "termine")
    tickets_svc.get_ticket(SLUG, ticket["id"])

    tickets_svc.add_run(SLUG, ticket, "coder-1", "work", "opus")
    tickets_svc.mark_run_completed(SLUG, ticket, "coder-1")

    reloaded = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert reloaded["runs"][0]["completed"] is True


def test_a_mutation_that_raises_leaves_the_store_intact_and_usable():
    """Une mutation qui échoue en plein vol ne laisse pas la connexion réutilisée dans une
    transaction ouverte : le ticket est inchangé et l'appel suivant fonctionne."""
    ticket = tickets_svc.create_ticket(SLUG, "titre d'origine", "fais")

    def failing_mutation(fresh: dict) -> None:
        fresh["title"] = "titre corrompu"
        raise RuntimeError("la mutation a échoué en plein vol")

    with pytest.raises(RuntimeError):
        _persistence._mutate(SLUG, ticket["id"], failing_mutation)

    assert tickets_svc.get_ticket(SLUG, ticket["id"])["title"] == "titre d'origine"
    tickets_svc.add_run(SLUG, ticket, "coder-2", "work", "opus")
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["runs"][0]["agent_id"] == "coder-2"


def test_moving_the_store_directory_never_serves_the_previous_database(tmp_path, monkeypatch):
    """Changer `TICKETS_DIR` (ce que fait la fixture d'isolation de CHAQUE test) doit
    ouvrir la nouvelle base, jamais continuer à lire l'ancienne connexion."""
    first = tickets_svc.create_ticket(SLUG, "base d'origine", "fais")

    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "autre-store")

    assert tickets_svc.get_ticket(SLUG, first["id"]) is None, "la base précédente est servie"
    second = tickets_svc.create_ticket(SLUG, "nouvelle base", "fais")
    assert tickets_svc.get_ticket(SLUG, second["id"])["title"] == "nouvelle base"
