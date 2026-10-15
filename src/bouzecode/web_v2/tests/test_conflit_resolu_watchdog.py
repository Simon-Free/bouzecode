# [desc] Un conflit résolu dans un worktree : le watchdog le constate et réveille le parent avec ce fait, sans jamais merger. [/desc]
"""Spec ticketing §5.4 / §5.7, principe B4. Avant le lot L4, `wake._reconcile_resolved_conflicts`
RE-MERGEAIT tout seul un ticket dont le conflit venait d'être résolu. Désormais le watchdog le
constate (« conflit résolu, prêt à intégrer ») et le parent manager est réveillé avec ce fait ;
c'est lui qui rappellera `integrate`. Vrai dépôt git, vrais fichiers d'agent ; seul le réveil
(`runner.continue_agent`, qui lancerait un vrai process) est remplacé par un enregistreur."""
from __future__ import annotations

import json

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import conflits, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import amener

from delivery_repo import (  # noqa: F401 — fixtures pytest
    SLUG, agents_dir, delivered_ticket, develop_repo, finished_agent, git_out, project,
)
from bouzecode.web_v2.runtime.runner import agent_reprise

PARENT = "manager00042"


def _parent_clos(agents_dir) -> None:
    session = agents_dir / f"{PARENT}.session.json"
    (agents_dir / f"{PARENT}.json").write_text(json.dumps({
        "agent_id": PARENT, "prompt": "orchestre", "model": "opus", "cwd": str(agents_dir),
        "pid": 4_000_001, "returncode": 0, "run_kind": "work", "profile": "manager",
        "started_at": "2026-10-05T09:00:00", "session_path": str(session),
    }), encoding="utf-8")
    session.write_text(json.dumps({"messages": [], "close_reason": "final_answer",
                                   "final_answer": "j'attends mes enfants"}), encoding="utf-8")
    store.invalidate_status(PARENT)
    agent_fiche._list_agents_cache.clear()


def test_un_conflit_resolu_reveille_le_parent_et_rien_n_est_merge(project, agents_dir,
                                                                 monkeypatch):
    reveils: list = []
    monkeypatch.setattr(wake, "WAKE_STATE_PATH", agents_dir / "wake_state.json")
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, message: reveils.append((agent.agent_id, message)))
    ticket = delivered_ticket(project, "enfant en conflit", produced="fix.py")
    git_out(ticket["worktree"]["worktree"], "add", "-A")
    git_out(ticket["worktree"]["worktree"], "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "résolution du conflit")  # le conflit a été résolu et commité
    tickets_svc.poser(SLUG, ticket, parent=PARENT,
                      integration={"conflict_files": ["fix.py"]})
    amener(SLUG, ticket, etats.INTEGRATE_STARTED, etats.CONFLICT_DETECTED, code="conflit")
    finished_agent(agents_dir, ticket["worktree"]["worktree"])
    _parent_clos(agents_dir)
    develop_avant = git_out(project, "rev-parse", "develop")

    for _ in range(3):
        wake.tick()

    assert git_out(project, "rev-parse", "develop") == develop_avant  # AUCUN merge d'office
    stored = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert (stored["state"], stored["state_reason"]["code"]) == (etats.CONFLICT, conflits.RESOLU)
    assert [parent for parent, _ in reveils] == [PARENT]  # réveillé UNE fois
    assert "CONFLIT RÉSOLU" in reveils[0][1] and ticket["id"] in reveils[0][1]
