"""Tests user-centric du backend /conversations : classification (4 natures),
tri need_input-first, exclusion auto des tests, archivage user, endpoint stale.

Aucun mock : on écrit de VRAIS artefacts d'agent (.json + sidecars + éventuel .ipc)
et on joue les endpoints HTTP réels via le test_client Flask."""
import json
import os

import pytest


def _write_agent(agents_dir, agent_id, prompt, *, parent="", running=False,
                 need_input=False):
    """Écrit un vrai {id}.json + sidecars. parent discrimine la nature :
    "" = user, "dispatcher:manual" = méta-agent, "<autre id>" = sous-agent.
    need_input=True → crée un dossier .ipc avec state.json awaiting_input."""
    pid = os.getpid() if running else 999_999_999
    ipc_dir = ""
    if need_input:
        ipc_path = agents_dir / f"{agent_id}.ipc"
        ipc_path.mkdir(exist_ok=True)
        (ipc_path / "state.json").write_text(
            json.dumps({"status": "awaiting_input", "question": "Continuer ?"}),
            encoding="utf-8",
        )
        ipc_dir = str(ipc_path)
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
        "ipc_dir": ipc_dir,
        "parent": parent,
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

    from bouzecode.web_v2.services.sessions import purge
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    # Registre soft-delete isolé dans le tmp (sinon on pollue ~/.bouzecode).
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")

    # user (parent vide)
    _write_agent(d, "usr001", "Corriger le bug de parsing dans parser.py")
    # méta-agent (dispatcher:manual)
    _write_agent(d, "meta01", "Analyse le repo et propose un plan",
                 parent="dispatcher:manual")
    # sous-agent (parent = un vrai agent id)
    _write_agent(d, "sub001", "Implémente la fonction X", parent="usr001")
    # test (titre 'test ...') → exclu par défaut
    _write_agent(d, "tst001", "test ping rapide")
    runner._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _agents(resp):
    return resp.get_json()["agents"]


def _by_key(agents, key):
    return next((a for a in agents if a["key"] == key), None)


def test_category_field_per_nature(client):
    """Chaque conversation porte un champ `category` reflétant sa nature."""
    agents = _agents(client.get("/api/sessions"))
    cats = {a["key"]: a["category"] for a in agents}
    assert cats["agent/usr001"] == "user"
    assert cats["agent/meta01"] == "meta"
    assert cats["agent/sub001"] == "subagent"


def test_tests_excluded_by_default(client):
    """Les conversations de test sont classées 'test' et exclues de la liste
    principale sans action manuelle (bouton 'Nettoyer les tests' inutile)."""
    agents = _agents(client.get("/api/sessions"))
    keys = {a["key"] for a in agents}
    assert "agent/tst001" not in keys


def test_tests_included_on_demand(client):
    """?include_tests=1 réintègre les conversations de test, classées 'test'."""
    agents = _agents(client.get("/api/sessions?include_tests=1"))
    test_agent = _by_key(agents, "agent/tst001")
    assert test_agent is not None
    assert test_agent["category"] == "test"


def test_need_input_field_and_sort_first(client, agents_dir):
    """Une conversation en attente d'input a need_input=True et remonte EN TÊTE."""
    from bouzecode.web_v2.runtime import runner

    # Ajoute un agent user en attente d'input, démarré AVANT les autres (donc
    # moins récent) : il doit néanmoins passer devant grâce au tri need_input-first.
    _write_agent(agents_dir, "wait01", "Question en attente", running=True,
                 need_input=True)
    runner._list_agents_cache.clear()

    agents = _agents(client.get("/api/sessions"))
    waiting = _by_key(agents, "agent/wait01")
    assert waiting is not None
    assert waiting["need_input"] is True
    # need_input remonte en tête de liste.
    assert agents[0]["key"] == "agent/wait01"
    # les autres ne sont pas en attente.
    assert _by_key(agents, "agent/usr001")["need_input"] is False


def test_archive_user_conversation(client):
    """POST /api/conversations/archive archive une conv 'user' (soft-delete
    réversible) : elle disparaît ensuite de la liste principale."""
    resp = client.post("/api/conversations/archive",
                       json={"keys": ["agent/usr001"]})
    body = resp.get_json()
    assert resp.status_code == 200
    assert "usr001" in body["archived"]  # id BRUT (convention endpoint, cf. skipped[].agent_id)

    agents = _agents(client.get("/api/sessions"))
    assert _by_key(agents, "agent/usr001") is None


def test_archive_reversible_via_restore(client):
    """Une conversation archivée peut être restaurée via /api/sessions/<key>/restore."""
    client.post("/api/conversations/archive", json={"keys": ["agent/usr001"]})
    resp = client.post("/api/sessions/agent/usr001/restore")
    assert resp.get_json()["ok"] is True
    agents = _agents(client.get("/api/sessions"))
    assert _by_key(agents, "agent/usr001") is not None


def test_archive_rejects_non_list(client):
    resp = client.post("/api/conversations/archive", json={"keys": "nope"})
    assert resp.status_code == 400


def test_stale_need_input_endpoint(client, agents_dir):
    """GET /api/conversations/stale-need-input remonte les conversations bloquées
    en need_input dont le process est MORT (orphelines)."""
    from bouzecode.web_v2.runtime import runner

    # process mort (running=False) MAIS état IPC awaiting_input → orphelin.
    _write_agent(agents_dir, "orph01", "Orpheline bloquée", need_input=True)
    runner._list_agents_cache.clear()

    resp = client.get("/api/conversations/stale-need-input")
    keys = {c["key"] for c in resp.get_json()["candidates"]}
    assert "agent/orph01" in keys
