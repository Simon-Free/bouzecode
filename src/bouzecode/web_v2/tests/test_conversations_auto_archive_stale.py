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
    from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche
    from bouzecode.web_v2.services.sessions import purge

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    agent_fiche._list_agents_cache.clear()
    agent_etat._ipc_state_cache.clear()

    _write_awaiting(d, "oldold", 100)          # >12h, pid mort  -> archivée
    _write_awaiting(d, "recent", 1)            # <12h            -> épargnée
    _write_awaiting(d, "runrun", 100, running=True)  # vivante   -> jamais touchée
    agent_fiche._list_agents_cache.clear()
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

    # Route `POST /api/conversations/auto-archive-stale` retirée (R11) : le service, directement.
    assert purge.auto_archive_stale_need_input()["archived"] == ["oldold"]

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


def test_une_question_orpheline_sans_date_lisible_compte_comme_ancienne(client, agents_dir):
    """Faute de date de départ lisible, on ne peut pas prouver qu'elle est récente : la
    question orpheline est archivée comme une vieille."""
    from bouzecode.web_v2.runtime.runner import agent_fiche

    _write_awaiting(agents_dir, "sansdate", 0)
    fiche = agents_dir / "sansdate.json"
    fiche.write_text(fiche.read_text(encoding="utf-8").replace(_iso_prefix(fiche), "pas-une-date"),
                     encoding="utf-8")
    agent_fiche._list_agents_cache.clear()

    from bouzecode.web_v2.services.sessions import purge
    assert sorted(purge.auto_archive_stale_need_input()["archived"]) == ["oldold", "sansdate"]


def _iso_prefix(fiche) -> str:
    return json.loads(fiche.read_text(encoding="utf-8"))["started_at"]
