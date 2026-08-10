"""Un agent archivé/purgé (dans purge.load_deleted) DISPARAÎT de la fleet ; il ne doit
donc JAMAIS ressortir « crashed » dans le bandeau des interrompus (/api/interrupted).

Régression du bug UI : agent affiché « crashed » alors qu'absent de la liste des agents.
Le fix aligne interrupted_report sur le MÊME critère que fleet._agent_tree_uncached
(`f"agent/{id}" in purge.load_deleted()`).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bouzecode.web_v2.services.work import _persistence, interrupted_report


def _fake_agent(agent_id: str):
    return SimpleNamespace(
        agent_id=agent_id,
        returncode=-1,          # mort
        ticket_id="T1",
        ticket_slug="proj",
        run_kind="work",
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isole TICKETS_DIR + REPORT_PATH, un ticket work méta avec un run crashé."""
    tickets_dir = tmp_path / "tickets"
    tickets_dir.mkdir()
    report_path = tmp_path / "interrupted_boot_report.json"
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(interrupted_report.tickets, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(interrupted_report, "REPORT_PATH", report_path)

    agent_id = "abc123"
    ticket = {
        "id": "T1",
        "parent": "",                      # pas de manager → méta-agent
        "runs": [{"agent_id": agent_id, "kind": "work"}],
    }
    # Semé dans le VRAI store (SQLite). Le fixture écrivait avant un `proj.json` legacy,
    # format que plus AUCUN code ne lit — le scan tournait donc à vide.
    _persistence._save("proj", [ticket])

    monkeypatch.setattr(
        interrupted_report.runner, "load_agent",
        lambda aid: _fake_agent(aid) if aid == agent_id else None)
    monkeypatch.setattr(
        interrupted_report.wake, "is_manager_parent", lambda parent: False)
    monkeypatch.setattr(
        interrupted_report.liveness, "classify_agent_run",
        lambda ticket, run: "crashed")

    return SimpleNamespace(
        agent_id=agent_id, report_path=report_path, tickets_dir=tickets_dir)


def _ids(report: dict) -> set[str]:
    return {it.get("agent_id") for it in report.get("items", [])}


def test_crashed_agent_present_when_not_deleted(env, monkeypatch):
    """Sanity : sans purge, l'agent crashé méta ressort bien dans le bandeau."""
    monkeypatch.setattr(interrupted_report.purge, "load_deleted", lambda: {})
    report = interrupted_report.build_boot_report([])
    assert env.agent_id in _ids(report)
    item = next(it for it in report["items"] if it["agent_id"] == env.agent_id)
    assert item["reason"] == "crashed"


def test_crashed_agent_absent_when_deleted(env, monkeypatch):
    """Fix : un agent dans purge.load_deleted (absent de la fleet) n'est JAMAIS
    listé « crashed », que ce soit via crashed_ids (cas a) ou via le scan tickets (cas c)."""
    monkeypatch.setattr(
        interrupted_report.purge, "load_deleted",
        lambda: {f"agent/{env.agent_id}": {"archived_at": "x"}})
    report = interrupted_report.build_boot_report([env.agent_id])
    assert env.agent_id not in _ids(report)
    assert report["items"] == []


def test_merge_previous_drops_deleted_agent(env, monkeypatch):
    """Fix (archivage POST-boot sans reboot) : un item du snapshot précédent dont
    l'agent est désormais deleted ne survit pas à la fusion."""
    # Snapshot précédent contient l'item crashé (agent encore vivant à l'époque).
    prev = {
        "boot_at": "old",
        "items": [{
            "agent_id": env.agent_id, "ticket": "T1", "slug": "proj",
            "kind": "work", "reason": "crashed", "action": "continue",
        }],
        "dismissed": False,
    }
    env.report_path.write_text(json.dumps(prev), encoding="utf-8")
    # L'agent vient d'être archivé, et son ticket retiré du board (archivé) : plus aucun
    # run à scanner. Le store n'efface JAMAIS un ticket, l'archivage EST le retrait.
    _persistence._save("proj", [{"id": "T1", "parent": "", "archived": True,
                                 "runs": [{"agent_id": env.agent_id, "kind": "work"}]}])
    monkeypatch.setattr(
        interrupted_report.purge, "load_deleted",
        lambda: {f"agent/{env.agent_id}": {"archived_at": "x"}})
    report = interrupted_report.build_boot_report([])
    assert env.agent_id not in _ids(report)
