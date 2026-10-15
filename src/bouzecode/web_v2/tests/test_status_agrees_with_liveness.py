# [desc] Un agent mort sans rien livrer ne s'affiche « terminé » sur AUCUNE surface. [/desc]
"""Le même ticket, trois statuts différents (cas vécu c08d9758 / ef0de6a96327).

L'agent est mort : returncode -1, session de quelques octets, AUCUN bloc produit. Au même
instant, /conversations affichait « mort ? » sur la vignette, « terminé » dans sa description
et dans le panneau de détail, tandis que le board disait « planté ». Annoncer « terminé » pour
un agent qui n'a RIEN livré est le pire des cas : c'est un travail livré annoncé qui n'existe
pas. Depuis L2, les surfaces lisent toutes `ticket.state` (`stopped{crashed}` constaté par le
watchdog) ; le panneau de conversation garde sa classification de vivacité de l'AGENT, qui doit
dire la même chose. Aucune ne dit « terminé ».

Aucun mock : un vrai fichier agent (PID inexistant → process réellement mort), une vraie
session close sans FinalAnswer, le vrai store SQLite, les vraies routes HTTP."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import _persistence, constats, fleet, projects, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats

SLUG = "demo-application"
AGENT = "ef0de6a96327"
PID_INEXISTANT = 4_000_000


@pytest.fixture(autouse=True)
def agents_dir(tmp_path, monkeypatch):
    """Store, projets et dossier d'agents à nous ; jamais de balayage du warm-pool réel."""
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: [])
    projets = tmp_path / "projects.json"
    projets.write_text(
        json.dumps([{"slug": SLUG, "name": "Demo", "path": str(tmp_path)}]),
        encoding="utf-8")
    monkeypatch.setattr(projects, "PROJECTS_PATH", projets)
    return tmp_path / "agents"


@pytest.fixture()
def client(monkeypatch):
    from bouzecode.web_v2.app import create_app
    # Le watchdog est un THREAD qui survivrait au test et tickerait sur le store des suivants.
    monkeypatch.setenv("BOUZECODE_WAKE_POLLER", "0")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _dead_agent_ticket(agents_dir, titre: str = "corrige le badge") -> dict:
    """Un ticket dont l'unique run est un agent MORT à 0 bloc : process disparu, aucun
    close_reason stampé, aucun final_answer — donc aucune livraison prouvée."""
    session = agents_dir / f"{AGENT}.session.json"
    (agents_dir / f"{AGENT}.json").write_text(json.dumps({
        "agent_id": AGENT, "prompt": titre, "model": "opus", "cwd": str(agents_dir),
        "pid": PID_INEXISTANT, "returncode": -1, "run_kind": "work",
        "started_at": "2026-07-28T09:00:00", "session_path": str(session),
    }), encoding="utf-8")
    session.write_text('{"messages": []}', encoding="utf-8")  # 0 bloc, pas de clôture
    store.invalidate_status(AGENT)
    ticket = tickets_svc.create_ticket(SLUG, titre, titre)
    tickets_svc.set_launching(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, AGENT, "work", "opus")
    return tickets_svc.get_ticket(SLUG, ticket["id"])


def _board_row(client, ticket_id: str) -> dict:
    rows = client.get(f"/api/projects/{SLUG}/tickets").get_json()["tickets"]
    return next(row for row in rows if row["id"] == ticket_id)


def test_the_three_surfaces_agree_that_a_dead_agent_never_delivered(client, agents_dir):
    """Board, détail du ticket et panneau de conversation disent tous « mort », jamais « terminé »."""
    ticket = _dead_agent_ticket(agents_dir)
    for _ in range(constats.MORTS_AVANT_CRASH):  # le watchdog constate la mort, comme en vrai
        wake.tick()

    board = _board_row(client, ticket["id"])
    detail = client.get(f"/api/projects/{SLUG}/tickets/{ticket['id']}").get_json()
    panneau = client.get(f"/api/sessions/agent/{AGENT}/blocks").get_json()

    assert (board["state"], board["status"]) == (etats.STOPPED, "planté")
    assert (detail["state"], detail["status"]) == (etats.STOPPED, "planté")
    # Le panneau de détail lit `status.liveness` (servi par la même classification) : c'est
    # ce champ qui remplace « terminé » par « planté » côté front.
    assert panneau["status"]["liveness"] == "crashed"
    assert panneau["status"]["interrupted"] is True
    assert "terminé" not in (board["status"], detail["status"])


def test_a_manual_done_cannot_repaint_a_dead_agent_as_finished(client, agents_dir):
    """Marquer le ticket « terminé » à la main ne peut pas inventer une livraison : seul un
    ticket LIVRÉ se clôt « accepté » (spec §4) ; un planté est refusé (409) et reste planté."""
    ticket = _dead_agent_ticket(agents_dir)
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    reponse = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/close",
                          json={"outcome": "accepted"})  # le user coche « terminé »

    board = _board_row(client, ticket["id"])
    detail = client.get(f"/api/projects/{SLUG}/tickets/{ticket['id']}").get_json()

    assert reponse.status_code == 409
    assert reponse.get_json()["error"]["code"] == "transition_refusee"
    assert board["state"] == detail["state"] == etats.STOPPED  # rien n'est prétendu livré
    assert board["status"] == detail["status"] == "planté"


def test_a_ticket_marked_done_after_a_real_delivery_stays_finished(client, agents_dir):
    """NON-RÉGRESSION : un agent qui a bien clos son tour (FinalAnswer) reste « terminé »."""
    ticket = _dead_agent_ticket(agents_dir)
    session = agents_dir / f"{AGENT}.session.json"
    session.write_text(json.dumps({
        "messages": [{"role": "assistant", "content": "voilà"}],
        "close_reason": "final_answer", "final_answer": "badge corrigé",
    }), encoding="utf-8")
    store.invalidate_status(AGENT)
    for _ in range(constats.MORTS_AVANT_CRASH):  # le watchdog lit la clôture : livré
        wake.tick()
    client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/close", json={"outcome": "accepted"})

    board = _board_row(client, ticket["id"])
    assert (board["state"], board["status"]) == (etats.CLOSED, "terminé")
    assert client.get(f"/api/sessions/agent/{AGENT}/blocks").get_json()[
        "status"]["interrupted"] is False


def test_a_live_agent_is_never_reported_as_dead_or_reviewable(client, agents_dir):
    """Piège inverse : un agent VIVANT (vrai PID) reste « en cours » sur les deux API, même
    après des passages du watchdog."""
    import os
    session = agents_dir / "vivant.session.json"
    (agents_dir / "vivant.json").write_text(json.dumps({
        "agent_id": "vivant", "prompt": "travaille", "model": "opus",
        "cwd": str(agents_dir), "pid": os.getpid(), "run_kind": "work",
        "started_at": "2026-07-28T09:00:00", "session_path": str(session),
    }), encoding="utf-8")
    session.write_text('{"messages": []}', encoding="utf-8")
    store.invalidate_status("vivant")
    ticket = tickets_svc.create_ticket(SLUG, "mission en vol", "travaille")
    tickets_svc.set_launching(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, "vivant", "work", "opus")
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()

    board = _board_row(client, ticket["id"])
    detail = client.get(f"/api/projects/{SLUG}/tickets/{ticket['id']}").get_json()

    assert board["status"] == detail["status"] == "en cours"
    assert board["state"] == detail["state"] == etats.RUNNING
