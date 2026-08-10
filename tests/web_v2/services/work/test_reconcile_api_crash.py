"""SPEC#3 — un run dont l'agent est mort avec close_reason='api_error' (session disque)
sans être completed ni avoir de verdict est un CRASH immédiat : _reconcile_api_crash
(symétrique de _reconcile_graceful_close) doit marquer le ticket crashed.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.services.work import wake


def _write_session(path, close_reason: str) -> None:
    path.write_text(json.dumps({"close_reason": close_reason}), encoding="utf-8")


def test_reconcile_api_crash_marks_ticket_crashed(tmp_path, monkeypatch):
    session = tmp_path / "codeur.session.json"
    _write_session(session, "api_error")

    # Agent mort (is_running False), session sur disque = source de vérité.
    class _DeadAgent:
        session_path = str(session)

    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: _DeadAgent())
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)

    captured = {}

    def _fake_report_crash(slug, ticket, done_agent):
        ticket["crashed"] = True
        captured["called"] = (slug, done_agent)

    # _act_report_crash est importé/appelé via le module workflow depuis wake.
    from bouzecode.web_v2.services.work import workflow
    monkeypatch.setattr(workflow, "_act_report_crash", _fake_report_crash)

    ticket = {
        "runs": [
            {"agent_id": "codeur", "kind": "work", "completed": False},
        ],
    }

    wake._reconcile_api_crash("myslug", ticket)

    assert ticket.get("crashed") is True, "le ticket doit passer crashed sur mort api_error"
    assert captured.get("called") == ("myslug", "")


def test_reconcile_api_crash_ignores_graceful(tmp_path, monkeypatch):
    session = tmp_path / "codeur.session.json"
    _write_session(session, "final_answer")

    class _DeadAgent:
        session_path = str(session)

    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: _DeadAgent())
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)

    from bouzecode.web_v2.services.work import workflow
    monkeypatch.setattr(
        workflow, "_act_report_crash",
        lambda *a: (_ for _ in ()).throw(AssertionError("ne doit pas crasher une fin gracieuse")),
    )

    ticket = {"runs": [{"agent_id": "codeur", "kind": "work", "completed": False}]}
    wake._reconcile_api_crash("myslug", ticket)
    assert ticket.get("crashed") is not True
