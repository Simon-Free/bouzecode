# [desc] Le watchdog ne relit plus les sessions d'un projet sans rien à réconcilier, et rattrape toujours un agent crashé. [/desc]
"""Charge de fond du watchdog `wake` (un tick toutes les 8 s, navigateur fermé).

Trois garanties : il ne travaille plus pour rien, il balaie quand même le warm-pool, et
il rattrape toujours un agent planté. Les coutures d'I/O (`runner.load_agent`,
`store.load_session_json`) sont espionnées par un compteur qui DÉLÈGUE ensuite à la vraie
implémentation — seul `fleet.sweep_warm_pool` est remplacé, car l'exécuter tuerait de
vrais process de la machine."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import _persistence, fleet, projects, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc

SLUG = "projet-du-watchdog"


@pytest.fixture(autouse=True)
def _own_store(tmp_path, monkeypatch):
    """Store de tickets à soi. La fixture autouse globale patche `tickets.TICKETS_DIR`, qui
    n'est qu'un ré-export : c'est `_persistence.TICKETS_DIR` que lit `_db_path()`."""
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")


@pytest.fixture()
def disk_reads(monkeypatch):
    """Compte les lectures de fichiers agent / de sessions, puis délègue au vrai code."""
    reads: list[str] = []
    real_load_agent, real_load_session = runner.load_agent, store.load_session_json

    def counting_load_agent(agent_id):
        reads.append(f"agent:{agent_id}")
        return real_load_agent(agent_id)

    def counting_load_session(path):
        reads.append(f"session:{path}")
        return real_load_session(path)

    monkeypatch.setattr(runner, "load_agent", counting_load_agent)
    monkeypatch.setattr(store, "load_session_json", counting_load_session)
    return reads


@pytest.fixture(autouse=True)
def _one_project(monkeypatch):
    monkeypatch.setattr(projects, "list_projects", lambda: [{"slug": SLUG, "name": "T"}])


@pytest.fixture(autouse=True)
def warm_pool_sweeps(monkeypatch):
    """Enregistre les balayages du warm-pool SANS déléguer : la vraie fonction tuerait des
    process warm de la machine (`AGENTS_DIR` n'est pas isolé en test)."""
    sweeps: list[str] = []
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: sweeps.append("balayé") or [])
    return sweeps


def _open_ticket(title: str) -> dict:
    return tickets_svc.create_ticket(SLUG, title, "fais le travail")


def test_a_merged_project_no_longer_reopens_any_agent_session_on_a_tick(disk_reads):
    """Un projet dont le seul ticket est mergé et fauché ne fait plus rouvrir la moindre session."""
    ticket = _open_ticket("livré et mergé")
    tickets_svc.add_run(SLUG, ticket, "coder-1", "work", "opus")
    tickets_svc.mark_run_completed(SLUG, ticket, "coder-1")
    ticket["worktree"] = {"state": "integrated", "worktree": "/wt"}
    ticket["reaped"] = True
    tickets_svc.update_ticket(SLUG, ticket)

    wake.tick()

    assert disk_reads == []


def test_the_warm_pool_is_swept_even_when_nothing_is_left_to_reconcile(warm_pool_sweeps):
    """Le warm-pool est balayé à chaque tick, même quand plus aucun ticket ne bouge."""
    ticket = _open_ticket("livré et mergé")
    tickets_svc.add_run(SLUG, ticket, "coder-3", "work", "opus")
    tickets_svc.mark_run_completed(SLUG, ticket, "coder-3")
    ticket["worktree"] = {"state": "integrated", "worktree": "/wt"}
    ticket["reaped"] = True
    tickets_svc.update_ticket(SLUG, ticket)

    wake.tick()

    assert warm_pool_sweeps == ["balayé"]


def test_a_ticket_whose_agent_is_still_open_is_still_inspected_on_a_tick(disk_reads):
    """Un ticket dont le run n'a pas clos sa comptabilité reste inspecté à chaque tick."""
    ticket = _open_ticket("travail en cours")
    tickets_svc.add_run(SLUG, ticket, "coder-2", "work", "opus")

    wake.tick()

    assert any(read.startswith("agent:coder-2") for read in disk_reads)


def test_a_crashed_agent_is_still_reported_as_planted_by_the_watchdog(disk_reads, monkeypatch,
                                                                     tmp_path):
    """Un agent lancé puis mort sans jamais clore son tour finit signalé « planté »."""
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    ticket = _open_ticket("agent qui plante")
    tickets_svc.add_run(SLUG, ticket, "coder-mort", "work", "opus")
    # L'agent a bien été lancé (son fichier existe) mais son process a disparu : ni
    # `completed` sur le run, ni close_reason gracieux dans sa session. C'est LE crash.
    (tmp_path / "coder-mort.json").write_text(json.dumps({
        "agent_id": "coder-mort", "prompt": "fais le travail", "model": "opus",
        "cwd": str(tmp_path), "pid": 4_000_000, "started_at": "2026-07-27T10:00:00",
        "session_path": str(tmp_path / "coder-mort.session.json"),
    }), encoding="utf-8")
    (tmp_path / "coder-mort.session.json").write_text('{"messages": []}', encoding="utf-8")

    for _ in range(wake._CRASH_DEAD_TICKS):
        wake.tick()

    reloaded = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert reloaded["crashed"] is True
    assert tickets_svc.derive_status(reloaded) == "planté"
