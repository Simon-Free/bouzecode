"""Rapport des agents interrompus au boot serveur web_v2.

On rejoue le VRAI flux : on pose sur disque des agents/tickets dans l'état où un
arrêt serveur les aurait laissés, on lance reconcile_dead_agents() +
build_boot_report() comme le boot réel (app.py::main), puis on interroge le
endpoint GET /api/interrupted via le Flask test client. Pas de mock.patch :
tout passe par les stores fichier réels, redirigés sur des tmpdir.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2 import app as app_module
from bouzecode.web_v2.services.work import interrupted_report, tickets
from bouzecode.web_v2.services.work import _persistence


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Redirige les 3 stores fichier (agents, tickets, rapport) sur des tmpdir."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    tickets_dir = tmp_path / "tickets"
    tickets_dir.mkdir()
    report_path = tmp_path / "interrupted_boot_report.json"
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    # `_persistence.TICKETS_DIR` = SOURCE du store SQLite (lue par `_db_path()`) ;
    # `tickets.TICKETS_DIR` n'en est qu'un ré-export.
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(tickets, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(interrupted_report, "REPORT_PATH", report_path)
    return {"agents": agents_dir, "tickets": tickets_dir, "report": report_path}


def _write_agent(agents_dir, agent_id, **overrides):
    """Écrit un fichier agent JSON minimal (les 6 champs requis + surcharges)."""
    data = {
        "agent_id": agent_id,
        "prompt": "fais le truc",
        "model": "sonnet",
        "cwd": str(agents_dir),
        "pid": 999999999,  # pid garanti mort → psutil.pid_exists False
        "started_at": datetime.utcnow().isoformat() + "Z",
        "returncode": None,
        "ipc_dir": "",  # get_ipc_state → unknown → reconcile stampe rc=-1
    }
    data.update(overrides)
    (agents_dir / f"{agent_id}.json").write_text(
        json.dumps(data), encoding="utf-8")


def _write_tickets(tickets_dir, slug, ticket_list):
    # Sème dans le VRAI store (SQLite) ; le format legacy `<slug>.json` n'existe plus.
    _persistence._save(slug, ticket_list)


@pytest.fixture
def client():
    return app_module.create_app().test_client()


def _boot(crashed_seed=None):
    """Rejoue le boot : reconcile (stampe les morts) → build_boot_report."""
    crashed_ids = runner.reconcile_dead_agents()
    return interrupted_report.build_boot_report(crashed_ids)


def test_crashed_agent_appears_in_interrupted(stores, client):
    # Un agent en vol (pid mort, IPC non-finished) au moment de l'arrêt serveur.
    _write_agent(stores["agents"], "aaaa11112222",
                 ticket_slug="proj", ticket_id="T1", run_kind="work")
    _boot()

    resp = client.get("/api/interrupted")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {it["agent_id"] for it in body["items"]}
    assert "aaaa11112222" in ids
    item = next(it for it in body["items"] if it["agent_id"] == "aaaa11112222")
    assert item["reason"] == "crashed"
    assert item["action"] == "continue"
    assert item["ticket"] == "T1"
    assert item["slug"] == "proj"


def test_launching_ticket_without_run_appears(stores, client):
    # Ticket en cours de lancement (spawn différé) dont le run n'a jamais démarré.
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T2", "prompt": "p", "launching": True, "runs": []},
    ])
    _boot()

    body = client.get("/api/interrupted").get_json()
    launching = [it for it in body["items"]
                 if it["reason"] == "launching_no_run"]
    assert len(launching) == 1
    assert launching[0]["ticket"] == "T2"
    assert launching[0]["slug"] == "proj"
    assert launching[0]["action"] == "launch"


def test_finished_agent_is_absent(stores, client):
    # Agent proprement clôturé (returncode 0) + ticket done → absent du rapport.
    _write_agent(stores["agents"], "bbbb33334444",
                 returncode=0, ticket_slug="proj", ticket_id="T3")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T3", "prompt": "p", "done": True,
         "runs": [{"agent_id": "bbbb33334444", "kind": "work"}]},
    ])
    _boot()

    body = client.get("/api/interrupted").get_json()
    ids = {it["agent_id"] for it in body["items"]}
    assert "bbbb33334444" not in ids
    assert not any(it["ticket"] == "T3" for it in body["items"])


def test_validate_subagent_absent_from_banner(stores, client):
    # CHANTIER 1 : un run 'validate' est un SOUS-AGENT (machinerie). Même mort sans
    # verdict, il n'apparaît PLUS dans le bandeau — il est repris automatiquement au
    # boot (auto_resume.resume_subagents). Il ne réapparaîtrait qu'en cas d'échec de
    # reprise (run['auto_resume_error'] posé) — testé dans test_auto_resume.py.
    _write_agent(stores["agents"], "cccc55556666",
                 returncode=0, ticket_slug="proj", ticket_id="T4",
                 run_kind="validate")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T4", "prompt": "p", "runs": [
            {"agent_id": "cccc55556666", "kind": "validate", "verdict": None},
        ]},
    ])
    _boot()

    body = client.get("/api/interrupted").get_json()
    item = next((it for it in body["items"]
                 if it["agent_id"] == "cccc55556666"), None)
    assert item is None


def test_dismiss_persists(stores, client):
    _write_agent(stores["agents"], "dddd77778888",
                 ticket_slug="proj", ticket_id="T5")
    _boot()

    assert client.get("/api/interrupted").get_json()["dismissed"] is False
    resp = client.post("/api/interrupted/dismiss")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    # Le rapport garde ses items mais est marqué masqué (persisté sur disque).
    body = client.get("/api/interrupted").get_json()
    assert body["dismissed"] is True
    assert len(body["items"]) >= 1
