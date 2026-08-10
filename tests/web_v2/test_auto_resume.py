"""CHANTIER 1 — reprise AUTO des sous-agents au boot + bandeau réservé aux méta-agents.

On joue le VRAI parcours de boot (reconcile → resume_subagents → build_boot_report)
au point d'entrée public, avec des stores fichier réels redirigés sur tmpdir et un
`resume_fn` injecté (fake pur en mémoire — AUCUN subprocess, AUCUN mock.patch).

Chaque scénario du cahier des charges a un test dédié :
  1. validate crashé (ticket ouvert)      → repris auto, ABSENT du bandeau.
  2. work d'un ticket user (parent vide)   → dans le bandeau, PAS repris.
  3. work enfant de manager (parent=agent) → repris auto.
  4. ticket done                            → ni bandeau ni reprise.
  5. double boot                            → pas de double reprise (flag persistant).
  6. échec de reprise                       → bandeau AVEC la raison.
"""
import json
from datetime import datetime

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import auto_resume, interrupted_report, tickets
from bouzecode.web_v2.services.work import _persistence


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Redirige les stores fichier (agents, tickets, rapport) sur des tmpdir réels."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    tickets_dir = tmp_path / "tickets"
    tickets_dir.mkdir()
    report_path = tmp_path / "interrupted_boot_report.json"
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    # `_persistence.TICKETS_DIR` est la SOURCE (base ouverte par `_db_path()`) ;
    # `tickets.TICKETS_DIR` n'en est qu'un ré-export. Le store est SQLite désormais.
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(tickets, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(interrupted_report, "REPORT_PATH", report_path)
    return {"agents": agents_dir, "tickets": tickets_dir, "report": report_path}


def _write_agent(agents_dir, agent_id, **overrides):
    """Agent JSON minimal, pid garanti mort → reconcile le stampe crashé (rc=-1)."""
    data = {
        "agent_id": agent_id,
        "prompt": "fais le truc",
        "model": "sonnet",
        "cwd": str(agents_dir),
        "pid": 999999999,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "returncode": None,
        "ipc_dir": "",
    }
    data.update(overrides)
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _write_tickets(tickets_dir, slug, ticket_list):
    # Sème dans le VRAI store (SQLite) ; le format legacy `<slug>.json` n'existe plus.
    _persistence._save(slug, ticket_list)


def _read_tickets(tickets_dir, slug):
    return _persistence._load(slug)


class _FakeResume:
    """resume_fn injectable : mémorise les appels et rend un id (succès) ou None/raise."""

    def __init__(self, result="new-agent-id"):
        self.result = result
        self.calls = []

    def __call__(self, agent_id, prompt):
        self.calls.append((agent_id, prompt))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _boot(resume_fn):
    """Rejoue l'ordre RÉEL du boot : reconcile (stampe les morts) → resume_subagents
    (reprend les sous-agents crashés) → build_boot_report (bandeau des méta restants)."""
    crashed_ids = runner.reconcile_dead_agents()
    attempts = auto_resume.resume_subagents(resume_fn=resume_fn)
    report = interrupted_report.build_boot_report(crashed_ids)
    return attempts, report


def _banner_ids(report):
    return {it["agent_id"] for it in report["items"]}


def test_1_crashed_validate_subagent_is_resumed_and_absent_from_banner(stores):
    _write_agent(stores["agents"], "val0aaaa1111", run_kind="validate")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T1", "prompt": "p", "parent": "manager-42", "runs": [
            {"agent_id": "val0aaaa1111", "kind": "validate", "verdict": None},
        ]},
    ])
    fake = _FakeResume()
    attempts, report = _boot(fake)

    assert fake.calls == [("val0aaaa1111", auto_resume.DEFAULT_RESUME_PROMPT)]
    assert "val0aaaa1111" not in _banner_ids(report)
    assert any(a["agent_id"] == "val0aaaa1111" and a["ok"] for a in attempts)
    # flag persistant + commentaire de trace posés sur le ticket.
    ticket = _read_tickets(stores["tickets"], "proj")[0]
    assert ticket["runs"][0].get("auto_resumed")
    assert any("[auto-resume]" in c["text"] for c in ticket.get("comments", []))


def test_2_meta_work_ticket_stays_in_banner_and_is_not_resumed(stores):
    # Ticket utilisateur : parent 'dispatcher:manual' → méta-agent, relance MANUELLE.
    _write_agent(stores["agents"], "meta0bbbb222", run_kind="work")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T2", "prompt": "p", "parent": "dispatcher:manual", "runs": [
            {"agent_id": "meta0bbbb222", "kind": "work"},
        ]},
    ])
    fake = _FakeResume()
    attempts, report = _boot(fake)

    assert fake.calls == []  # méta JAMAIS repris auto
    assert "meta0bbbb222" in _banner_ids(report)
    item = next(it for it in report["items"] if it["agent_id"] == "meta0bbbb222")
    assert item["reason"] == "crashed"
    assert not any(a["agent_id"] == "meta0bbbb222" for a in attempts)


def test_2b_meta_work_empty_parent_stays_in_banner(stores):
    # parent vide/absent → aussi un méta-agent.
    _write_agent(stores["agents"], "meta0cccc333", run_kind="work")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T2b", "prompt": "p", "runs": [
            {"agent_id": "meta0cccc333", "kind": "work"},
        ]},
    ])
    fake = _FakeResume()
    _, report = _boot(fake)

    assert fake.calls == []
    assert "meta0cccc333" in _banner_ids(report)


def test_3_child_work_of_manager_is_resumed(stores):
    # parent = agent_id d'un manager (pas 'dispatcher:*') → sous-agent dispatché.
    _write_agent(stores["agents"], "child0ddd444", run_kind="work")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T3", "prompt": "p", "parent": "manager-agent-777", "runs": [
            {"agent_id": "child0ddd444", "kind": "work"},
        ]},
    ])
    fake = _FakeResume()
    attempts, report = _boot(fake)

    assert fake.calls == [("child0ddd444", auto_resume.DEFAULT_RESUME_PROMPT)]
    assert "child0ddd444" not in _banner_ids(report)
    assert any(a["agent_id"] == "child0ddd444" and a["ok"] for a in attempts)


def test_7_reaped_ticket_is_not_resumed_even_if_subagent_crashed(stores):
    # Ticket déjà mergé/reapé (worktree nettoyé) mais son run sous-agent 'work'
    # est encore crashé : la reprise AUTO doit REFUSER (bug 17d4122a) — jamais
    # de respawn dans le dossier fantôme, avec une raison explicite persistée.
    _write_agent(stores["agents"], "reaped0hhh88", run_kind="work")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T7", "prompt": "p", "parent": "manager-agent-777",
         "reaped": True, "runs": [
            {"agent_id": "reaped0hhh88", "kind": "work"},
        ]},
    ])
    fake = _FakeResume()
    attempts, _ = _boot(fake)

    assert fake.calls == []  # AUCUN respawn dans le worktree fantôme
    attempt = next(a for a in attempts if a["agent_id"] == "reaped0hhh88")
    assert attempt["ok"] is False
    assert "mergé" in attempt["error"] or "reapé" in attempt["error"]
    ticket = _read_tickets(stores["tickets"], "proj")[0]
    assert ticket["runs"][0].get("auto_resumed")  # flag → pas de retry au boot suivant
    assert ticket["runs"][0].get("auto_resume_error")
    assert any("REFUSÉE" in c["text"] for c in ticket.get("comments", []))


def test_4_done_ticket_is_neither_resumed_nor_in_banner(stores):
    _write_agent(stores["agents"], "done0eee5555", run_kind="validate")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T4", "prompt": "p", "parent": "manager-9", "done": True, "runs": [
            {"agent_id": "done0eee5555", "kind": "validate", "verdict": None},
        ]},
    ])
    fake = _FakeResume()
    attempts, report = _boot(fake)

    assert fake.calls == []
    assert "done0eee5555" not in _banner_ids(report)
    assert attempts == []


def test_5_double_boot_does_not_resume_twice(stores):
    _write_agent(stores["agents"], "twice0fff666", run_kind="validate")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T5", "prompt": "p", "parent": "manager-1", "runs": [
            {"agent_id": "twice0fff666", "kind": "validate", "verdict": None},
        ]},
    ])
    fake = _FakeResume()
    _boot(fake)  # 1er boot → reprend une fois
    assert len(fake.calls) == 1

    # 2e boot (le flag persistant run['auto_resumed'] a été écrit sur disque).
    fake2 = _FakeResume()
    attempts2, _ = _boot(fake2)
    assert fake2.calls == []  # AUCUNE seconde reprise
    assert attempts2 == []


def test_6_failed_resume_reappears_in_banner_with_reason(stores):
    _write_agent(stores["agents"], "fail0ggg7777", run_kind="validate")
    _write_tickets(stores["tickets"], "proj", [
        {"id": "T6", "prompt": "p", "parent": "manager-3", "runs": [
            {"agent_id": "fail0ggg7777", "kind": "validate", "verdict": None},
        ]},
    ])
    fake = _FakeResume(result=None)  # reprise échoue (agent introuvable)
    attempts, report = _boot(fake)

    assert fake.calls == [("fail0ggg7777", auto_resume.DEFAULT_RESUME_PROMPT)]
    item = next((it for it in report["items"]
                 if it["agent_id"] == "fail0ggg7777"), None)
    assert item is not None
    assert item["reason"] == "auto_resume_failed"
    assert item["error"]  # raison non vide
    assert any(not a["ok"] for a in attempts)
    # erreur persistée sur le run.
    ticket = _read_tickets(stores["tickets"], "proj")[0]
    assert ticket["runs"][0].get("auto_resume_error")
