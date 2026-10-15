"""SPEC#2 — refresh_agent_status ne doit PLUS forcer returncode=0 à la mort d'un pid
disparu quand la session porte un close_reason non-gracieux (api_error). Le vrai rc
étant irrécupérable (Popen non retenu), la SOURCE DE VÉRITÉ est close_reason sur disque.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.runtime.runner.agent_etat import refresh_agent_status
from bouzecode.web_v2.runtime.runner.agent_fiche import Agent


_DEAD_PID = 2_000_000_000  # pid quasi-certainement inexistant


def _make_agent(tmp_path, close_reason: str) -> Agent:
    session = tmp_path / "agent.session.json"
    session.write_text(json.dumps({"close_reason": close_reason}), encoding="utf-8")
    return Agent(
        agent_id="deadagent",
        prompt="p",
        model="m",
        cwd=str(tmp_path),
        pid=_DEAD_PID,
        started_at="2026-07-07T00:00:00Z",
        session_path=str(session),
    )


def test_api_error_session_forces_returncode_minus_one(tmp_path, monkeypatch):
    # _save écrit dans AGENTS_DIR — le redirige vers tmp pour ne rien polluer.
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", tmp_path)
    agent = _make_agent(tmp_path, close_reason="api_error")
    refreshed = refresh_agent_status(agent)
    assert refreshed.returncode == -1, (
        f"un mort api_error doit être rc=-1 (crash), obtenu {refreshed.returncode}"
    )


def test_graceful_session_keeps_returncode_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", tmp_path)
    agent = _make_agent(tmp_path, close_reason="final_answer")
    refreshed = refresh_agent_status(agent)
    assert refreshed.returncode == 0, (
        f"une fin gracieuse reste rc=0, obtenu {refreshed.returncode}"
    )
