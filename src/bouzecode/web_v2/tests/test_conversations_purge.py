"""User-centric: onglet Conversations — détection + purge sûre des conversations de test.

On écrit de vrais fichiers agent {id}.json dans un AGENTS_DIR temporaire, puis on
joue les endpoints réels via le client Flask. On vérifie que:
  - le preview ne remonte QUE les agents de test non-running,
  - la purge déplace (soft-delete) les artefacts vers _trash/{id}/,
  - une vraie conversation user n'est JAMAIS touchée,
  - un agent qui tourne n'est jamais purgé.
Aucun mock: uv + monkeypatch de AGENTS_DIR (pas unittest.mock).
"""
import json
import os

import pytest

from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction


def _write_agent(agents_dir, agent_id, prompt, *, running=False):
    """Écrit un vrai {id}.json + un sidecar .session.json + .out.log."""
    pid = os.getpid() if running else 999_999_999  # pid courant = vivant ; sinon mort
    data = {
        "agent_id": agent_id,
        "prompt": prompt,
        "model": "claude-sonnet",
        "cwd": "/tmp",
        "pid": pid,
        "started_at": f"2026-06-01T10:00:0{len(agent_id) % 10}Z",
        "returncode": None if running else 0,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": []}), encoding="utf-8"
    )
    (agents_dir / f"{agent_id}.out.log").write_text("log", encoding="utf-8")


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    runner._list_agents_cache.clear()
    # purge.TRASH_DIR est figé à l'import → le repointer sur le tmp AGENTS_DIR.
    from bouzecode.web_v2.services.sessions import purge
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")

    # test conversations (à purger, non-running)
    _write_agent(d, "aaaaaa", "test typology sur projet foo")
    _write_agent(d, "bbbbbb", "Test ping rapide")
    # vraie conversation user (jamais touchée)
    _write_agent(d, "cccccc", "Corriger le bug de parsing dans parser.py")
    # test conversation MAIS en cours d'exécution (jamais purgée)
    _write_agent(d, "dddddd", "test running keep", running=True)
    runner._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_preview_only_lists_non_running_test_conversations(client):
    resp = client.get("/api/conversations/test-candidates")
    assert resp.status_code == 200
    ids = {c["agent_id"] for c in resp.get_json()["candidates"]}
    assert ids == {"aaaaaa", "bbbbbb"}  # ni la vraie conv, ni la running


def test_purge_soft_deletes_test_conversations(client, agents_dir, monkeypatch):
    """Purger des conversations de test met leurs fichiers à la corbeille, sans les effacer.

    `destruction_permitted` rend ce chemin INERTE sous pytest depuis les dégâts du
    2026-07-28 (des fixtures avaient purgé le parc réel) : prouver le déplacement réel
    demande de lever le garde-fou explicitement, sur le parc jetable de la fixture."""
    autoriser_la_destruction(monkeypatch)

    resp = client.post(
        "/api/conversations/purge-tests",
        json={"agent_ids": ["aaaaaa", "bbbbbb"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["purged"]) == {"aaaaaa", "bbbbbb"}
    # Les artefacts sont DÉPLACÉS (soft-delete), pas supprimés.
    for aid in ("aaaaaa", "bbbbbb"):
        assert not (agents_dir / f"{aid}.json").exists()
        assert (agents_dir / "_trash" / aid / f"{aid}.json").exists()
        assert (agents_dir / "_trash" / aid / f"{aid}.session.json").exists()


def test_purge_refuses_real_conversation(client, agents_dir):
    resp = client.post(
        "/api/conversations/purge-tests",
        json={"agent_ids": ["cccccc"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["purged"] == []
    assert body["skipped"][0]["agent_id"] == "cccccc"
    # La vraie conversation est intacte sur disque.
    assert (agents_dir / "cccccc.json").exists()


def test_purge_refuses_running_test_conversation(client, agents_dir, monkeypatch):
    """Une conversation de test encore vivante est refusée, garde-fou levé ou non.

    Le motif rendu est « agent vivant » : le refus ne repose plus sur `_is_running` (qui
    écrivait `returncode` avant de le relire, et déclarait donc morts des agents en vol),
    mais sur `est_vivant`, qui interroge l'OS. On lève le garde-fou pour prouver que c'est
    bien CE refus qui protège l'agent, et non l'inertie de la suite."""
    autoriser_la_destruction(monkeypatch)

    resp = client.post(
        "/api/conversations/purge-tests",
        json={"agent_ids": ["dddddd"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["purged"] == []
    assert body["skipped"][0]["reason"] == "agent vivant"
    assert (agents_dir / "dddddd.json").exists()
