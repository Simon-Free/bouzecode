# [desc] Un rafraîchissement de verdicts n'écrase jamais une écriture concurrente sur un autre ticket. [/desc]
"""Perte d'écriture SILENCIEUSE constatée en production le 2026-07-27.

`GET /api/projects/<slug>/tickets` rafraîchit les verdicts à partir d'une liste chargée
AVANT le rafraîchissement, puis réécrit TOUTE cette liste. Un autre écrivain (agent CLI,
autre requête, script) qui modifiait un ticket entre la lecture et l'écriture voyait sa
modification réécrasée par l'instantané périmé — sans erreur, sans log, sans trace.
Le travail n'était récupéré que parce que son auteur relisait ses propres écritures.

Ce que le store doit garantir : rafraîchir des verdicts ne touche QUE les tickets dont un
verdict a réellement changé, et seulement le champ `verdict` de leur version FRAÎCHE."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import _persistence, tickets

SLUG = "proj"
VALIDATOR = "le-validateur"


@pytest.fixture()
def parc(monkeypatch, tmp_path):
    """Le parc d'agents : un validateur TERMINÉ dont la session livre « VERDICT: OK »."""
    session = tmp_path / "validateur.session.json"
    session.write_text(
        json.dumps({"messages": [{"role": "assistant", "content": "Tests verts.\nVERDICT: OK"}]}),
        encoding="utf-8",
    )
    agent = runner.Agent(agent_id=VALIDATOR, prompt="", model="", cwd="", pid=0,
                         started_at="", session_path=str(session))
    monkeypatch.setattr(runner, "load_agent", lambda aid: agent if aid == VALIDATOR else None)
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": "finished"})
    monkeypatch.setattr(tickets, "_verdict_cache", {})  # aucun verdict mémorisé d'un autre test
    return agent


@pytest.fixture()
def tickets_written(monkeypatch) -> list[str]:
    """Les ids des tickets RÉELLEMENT écrits en base — espion sur la couture d'écriture
    du store, qui enregistre puis délègue à la vraie implémentation."""
    written: list[str] = []
    real_upsert = _persistence._upsert_one

    def _spy(conn, slug, ticket):
        written.append(ticket["id"])
        real_upsert(conn, slug, ticket)

    monkeypatch.setattr(_persistence, "_upsert_one", _spy)
    return written


def _seed(title: str, runs: list[dict]) -> str:
    """Un ticket dans le store, avec ses runs. Renvoie son id."""
    ticket = tickets.create_ticket(SLUG, title, "prompt")
    ticket["runs"] = runs
    tickets.update_ticket(SLUG, ticket)
    return ticket["id"]


def _board() -> tuple[str, str, list[dict]]:
    """Deux tickets — un sans run, un avec une validation terminée — et l'instantané
    que la route charge AVANT de rafraîchir. Renvoie (id du calme, id du validé, snapshot)."""
    quiet = _seed("ticket tranquille", [])
    validated = _seed("ticket validé", [
        {"agent_id": VALIDATOR, "kind": "validate", "model": "m",
         "started_at": "2026-07-27T10:00:00", "verdict": None},
    ])
    return quiet, validated, tickets.list_tickets(SLUG)


def test_a_concurrent_edit_survives_a_verdict_refresh(parc):
    """Un commentaire posé pendant le rafraîchissement n'est pas réécrasé par l'instantané."""
    quiet, _validated, snapshot = _board()

    # Entre la lecture de l'instantané et son écriture, un autre écrivain commente ce ticket.
    tickets.add_comment(SLUG, tickets.get_ticket(SLUG, quiet), "écrit en parallèle", False)

    tickets.refresh_verdicts(SLUG, snapshot)

    fresh = tickets.get_ticket(SLUG, quiet)
    assert [c["text"] for c in fresh["comments"]] == ["écrit en parallèle"]


def test_a_concurrent_edit_on_the_refreshed_ticket_survives_too(parc):
    """Même le ticket dont le verdict est parsé garde les champs modifiés en parallèle."""
    _quiet, validated, snapshot = _board()

    tickets.add_comment(SLUG, tickets.get_ticket(SLUG, validated), "relecture en cours", False)

    tickets.refresh_verdicts(SLUG, snapshot)

    fresh = tickets.get_ticket(SLUG, validated)
    assert [c["text"] for c in fresh["comments"]] == ["relecture en cours"]
    assert fresh["runs"][0]["verdict"] == "OK", "le verdict doit tout de même être persisté"


def test_a_refresh_only_writes_the_tickets_it_changed(parc, tickets_written):
    """Un ticket dont aucun verdict n'a bougé n'est pas réécrit du tout."""
    _quiet, validated, snapshot = _board()

    tickets.refresh_verdicts(SLUG, snapshot)

    assert tickets_written == [validated]


def test_a_refresh_without_any_new_verdict_writes_nothing(parc, tickets_written):
    """Rafraîchir un board déjà à jour ne provoque aucune écriture."""
    _quiet, _validated, snapshot = _board()
    tickets.refresh_verdicts(SLUG, snapshot)  # 1er passage : le verdict est parsé et persisté
    tickets_written.clear()

    tickets.refresh_verdicts(SLUG, tickets.list_tickets(SLUG))

    assert tickets_written == []


def test_the_live_run_state_is_never_persisted(parc):
    """L'état live d'un run (`state`, `key`) reste en mémoire : il ne va jamais en base."""
    _quiet, validated, snapshot = _board()

    tickets.refresh_verdicts(SLUG, snapshot)

    run = tickets.get_ticket(SLUG, validated)["runs"][0]
    assert "state" not in run and "key" not in run


def test_a_read_only_refresh_writes_nothing(parc, tickets_written):
    """`persist=False` (compteurs home) rafraîchit en mémoire sans toucher au store."""
    _quiet, _validated, snapshot = _board()
    tickets_written.clear()

    tickets.refresh_verdicts(SLUG, snapshot, persist=False)

    assert tickets_written == []
    assert snapshot[0]["runs"][0]["verdict"] == "OK", "le refresh mémoire reste fait"
