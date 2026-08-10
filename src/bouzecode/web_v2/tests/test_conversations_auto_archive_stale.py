"""User-centric: onglet Conversations — auto-archivage des 'need input' orphelines.

Un agent qui a posé une question (AskUserQuestion) persiste l'état IPC 'awaiting_input'
puis quitte : sa conversation reste éternellement 'à répondre'. Passé 12h, on l'archive
(réversible). On vérifie qu'une question VIEILLE (>12h, pid mort) est archivée, qu'une
question RÉCENTE (<12h) est épargnée, et qu'un agent VIVANT n'est jamais touché.
Aucun mock : uv + monkeypatch d'AGENTS_DIR (pas unittest.mock).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _write_awaiting(agents_dir, agent_id, hours_ago, *, running=False):
    """Agent au statut IPC 'awaiting_input', pid mort (sauf running=True)."""
    pid = os.getpid() if running else 999_999_999
    data = {
        "agent_id": agent_id,
        "prompt": f"Conversation {agent_id}",
        "model": "claude-sonnet",
        "cwd": "/tmp",
        "pid": pid,
        "started_at": _iso(hours_ago),
        "returncode": None if running else 0,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(agents_dir / f"{agent_id}.ipc"),
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
    (agents_dir / f"{agent_id}.out.log").write_text("log", encoding="utf-8")
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    (ipc / "state.json").write_text(
        json.dumps({"status": "awaiting_input", "question": "Continuer ?"}), encoding="utf-8"
    )


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import purge

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    runner._list_agents_cache.clear()
    runner._ipc_state_cache.clear()

    _write_awaiting(d, "oldold", 100)          # >12h, pid mort  -> archivée
    _write_awaiting(d, "recent", 1)            # <12h            -> épargnée
    _write_awaiting(d, "runrun", 100, running=True)  # vivante   -> jamais touchée
    runner._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_auto_archive_only_hits_old_dead_awaiting(client, agents_dir):
    """Seule la question abandonnée depuis >12h quitte la liste des orphelines à traiter.

    Ce test exigeait auparavant que l'archivage DÉPLACE `oldold.json` vers `_trash/` : le
    produit a retiré ce déplacement, qui avait rendu un manager vivant injoignable
    (`load_agent` → None → 404 sur /continue) le 2026-07-28. L'archivage n'inscrit plus que
    la clé au registre — et c'est ce registre que la liste des orphelines filtre."""
    from bouzecode.web_v2.services.sessions import purge

    assert _stale_ids(client) == {"oldold", "recent"}  # runrun est vivante : jamais candidate

    resp = client.post("/api/conversations/auto-archive-stale")
    assert resp.status_code == 200
    assert resp.get_json()["archived"] == ["oldold"]

    # La vieille orpheline sort de la liste à traiter ; la question récente y reste.
    assert _stale_ids(client) == {"recent"}
    assert purge.load_deleted()["agent/oldold"]["reason"] == "archived"
    # Rien n'a bougé sur le disque : les trois conversations restent joignables.
    for agent_id in ("oldold", "recent", "runrun"):
        assert (agents_dir / f"{agent_id}.json").exists()
    assert not (agents_dir / "_trash").exists()


def _stale_ids(client) -> set[str]:
    """Les conversations que l'UI propose d'archiver (questions orphelines)."""
    resp = client.get("/api/conversations/stale-need-input")
    assert resp.status_code == 200
    return {c["agent_id"] for c in resp.get_json()["candidates"]}


def test_age_hours_parses_and_defaults_to_infinity():
    from bouzecode.web_v2.services.sessions import purge

    assert purge._age_hours(None) == float("inf")
    assert purge._age_hours("pas-une-date") == float("inf")
    assert purge._age_hours(_iso(24)) >= 23.0
