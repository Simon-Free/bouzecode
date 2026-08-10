# [desc] Tests que /interrupt écrit cancel.flag (interruption douce) sans tuer le process, via client Flask réel. [/desc]
"""Vérifie l'interruption DOUCE d'un agent web via le test client Flask réel.

On teste le VRAI comportement : l'endpoint /interrupt appelle
runner.graceful_cancel_agent qui écrit le fichier cancel.flag dans l'ipc_dir de
l'agent SANS tuer le process (contrairement à /kill). On monkeypatch uniquement
runner.load_agent pour retourner un agent factice pointant vers un ipc_dir tmp ;
graceful_cancel_agent reste RÉEL (pas de mock)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture()
def _ipc_dir(tmp_path):
    d = tmp_path / "ipc"
    d.mkdir()
    return d


@pytest.fixture()
def client(_ipc_dir, monkeypatch):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.routes import sessions as sessions_route

    # returncode + pid inexistant → runner.is_running(agent) renvoie False proprement
    # (l'escalade de /interrupt l'appelle ; sans returncode → AttributeError).
    fake_agent = SimpleNamespace(
        agent_id="abc123", ipc_dir=str(_ipc_dir), pid=2**31 - 1, returncode=None
    )

    def _load_agent(agent_id):
        return fake_agent if agent_id == "abc123" else None

    # Only the lookup is faked; graceful_cancel_agent stays real.
    monkeypatch.setattr(sessions_route.runner, "load_agent", _load_agent)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_interrupt_writes_cancel_flag_softly(client, _ipc_dir):
    """POST /interrupt écrit cancel.flag (interruption douce) et NE tue PAS le process."""
    from bouzecode.web_v2.runtime import ipc

    paths = ipc.from_dir(str(_ipc_dir))
    assert ipc.is_cancelled(paths) is False  # rien avant

    resp = client.post("/api/agents/abc123/interrupt")

    assert resp.status_code == 200
    # `escalated: False` = le process n'a PAS été tué : c'est bien la voie douce.
    assert resp.get_json() == {"ok": True, "escalated": False}
    # Le VRAI graceful_cancel_agent a posé le drapeau d'annulation.
    assert ipc.is_cancelled(paths) is True


def test_interrupt_unknown_agent_returns_404(client):
    resp = client.post("/api/agents/nope/interrupt")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_interrupt_escalates_to_kill_when_still_running(client, _ipc_dir, monkeypatch):
    """Agent COINCÉ (toujours vivant après la grâce) → escalade vers kill_agent."""
    from bouzecode.web_v2.runtime import ipc
    from bouzecode.web_v2.routes import sessions as sessions_route

    monkeypatch.setattr(sessions_route.runner, "is_running", lambda agent: True)
    monkeypatch.setattr(sessions_route.time, "sleep", lambda *_a, **_k: None)
    killed = []
    monkeypatch.setattr(sessions_route.runner, "kill_agent",
                        lambda agent: killed.append(agent)
                        or {"signalled": True, "twins": 0, "error": ""})

    resp = client.post("/api/agents/abc123/interrupt")

    assert resp.status_code == 200
    # L'escalade est AVOUÉE : /interrupt n'est pas purement doux, la réponse le dit.
    assert resp.get_json() == {"ok": True, "escalated": True}
    # graceful d'abord : le flag doux est bien posé.
    assert ipc.is_cancelled(ipc.from_dir(str(_ipc_dir))) is True
    # puis escalade : l'agent toujours vivant a été tué.
    assert len(killed) == 1


def test_interrupt_no_kill_when_stopped_gracefully(client, monkeypatch):
    """Agent qui s'arrête proprement (plus vivant) → PAS d'escalade kill."""
    from bouzecode.web_v2.routes import sessions as sessions_route

    monkeypatch.setattr(sessions_route.runner, "is_running", lambda agent: False)
    monkeypatch.setattr(sessions_route.time, "sleep", lambda *_a, **_k: None)
    killed = []
    monkeypatch.setattr(sessions_route.runner, "kill_agent", lambda agent: killed.append(agent))

    resp = client.post("/api/agents/abc123/interrupt")

    assert resp.status_code == 200
    assert killed == []


def test_push_followup_clears_cancel_flag(_ipc_dir, monkeypatch):
    """Reprise CHAUDE : un nouveau message utilisateur (followup) doit EFFACER un
    cancel.flag pendant, sinon le tour relancé s'auto-interrompt aussitôt (boucle
    « l'agent s'interromp en permanence malgré les messages »)."""
    from bouzecode.web_v2.runtime import ipc, runner

    paths = ipc.from_dir(str(_ipc_dir))
    paths.cancel.write_text("", encoding="utf-8")  # interruption pendante
    assert ipc.is_cancelled(paths) is True

    monkeypatch.setattr(runner, "_save", lambda agent: None)
    agent = SimpleNamespace(ipc_dir=str(_ipc_dir), finished_at="x", returncode=0)

    runner._push_followup(agent, "nouveau message")

    assert ipc.is_cancelled(paths) is False  # le flag a été consommé
    assert paths.followup.read_text(encoding="utf-8") == "nouveau message"


def test_push_answer_clears_cancel_flag(_ipc_dir, monkeypatch):
    """Reprise CHAUDE d'une pause AskUserQuestion : la réponse doit AUSSI effacer un
    cancel.flag pendant (même bug de boucle d'auto-interruption)."""
    from bouzecode.web_v2.runtime import ipc, runner

    paths = ipc.from_dir(str(_ipc_dir))
    paths.cancel.write_text("", encoding="utf-8")
    assert ipc.is_cancelled(paths) is True

    monkeypatch.setattr(runner, "_save", lambda agent: None)
    agent = SimpleNamespace(ipc_dir=str(_ipc_dir), finished_at="x", returncode=0)

    runner._push_answer(agent, "ma réponse")

    assert ipc.is_cancelled(paths) is False
    assert paths.answer.read_text(encoding="utf-8") == "ma réponse"
