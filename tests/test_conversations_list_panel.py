"""Tests du PANNEAU LISTE de l'onglet Conversations (web_v2).

Couvre les améliorations apportées à la colonne de gauche :
- (a) chargement rapide : list_agent_sessions() ne parcourt PAS les sessions daily ;
- (d) tri : les conversations en attente d'input user remontent EN HAUT ;
- (e) chemin JSON de session : exposé par node + route de téléchargement.

User-centric, sans unittest.mock : on injecte des fakes purs via monkeypatch.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.sessions import store as _store
from bouzecode.web_v2.services.work import fleet as _fleet
from bouzecode.web_v2.services.work import projects as _projects
from bouzecode.web_v2.services.work import repos as _repos


def _fake_agent(agent_id: str, *, started_at: str, session_path: str = "",
                prompt: str = "", cwd: str = "", model: str = "") -> agent_fiche.Agent:
    """Vrai runner.Agent : un sosie à champs figés se périme dès qu'`Agent` gagne un
    champ lu par agent_tree (pid/ipc_dir l'ont déjà fait). pid=0 => jamais « warm »."""
    return agent_fiche.Agent(
        agent_id=agent_id,
        prompt=prompt or f"prompt {agent_id}",
        model=model,
        cwd=cwd,
        pid=0,
        started_at=started_at,
        session_path=session_path or f"/tmp/{agent_id}.json",
    )


# ---------------------------------------------------------------------------
# (a) list_agent_sessions() ne touche PAS aux sessions daily
# ---------------------------------------------------------------------------
def test_list_agent_sessions_skips_daily(monkeypatch, tmp_path):
    """La liste de l'onglet Conversations n'affiche que les agents web.

    On garantit qu'aucune session daily n'est renvoyée (pas de clé 'days',
    résultat = simple liste d'agents) : c'est ce qui rend le chargement rapide,
    car on évite de scanner les gros JSON quotidiens.
    """
    session_file = tmp_path / "sess.json"
    session_file.write_text('{"first_message": "salut", "model": "gpt", "turn_count": 3,'
                            ' "saved_at": "2026-07-02T10:00:00"}', encoding="utf-8")
    agent = _fake_agent("aaa", started_at="2026-07-02T09:00:00",
                        session_path=str(session_file))
    monkeypatch.setattr(agent_registre, "list_agents", lambda: [agent])
    monkeypatch.setattr(_store, "agent_status",
                        lambda a: {"state": "running", "question": "", "options": [],
                                   "allow_freetext": True, "returncode": None})

    result = _store.list_agent_sessions()

    assert isinstance(result, list)  # PAS un dict {agents, days}
    assert len(result) == 1
    row = result[0]
    assert row["key"] == "agent/aaa"
    assert row["turn_count"] == 3
    assert row["status"]["state"] == "running"


# ---------------------------------------------------------------------------
# (d) + (e) agent_tree() : awaiting en tête + session_path exposé
# ---------------------------------------------------------------------------
def _patch_tree_deps(monkeypatch):
    monkeypatch.setattr(_projects, "list_projects", lambda: [])
    monkeypatch.setattr(_projects, "project_for_cwd", lambda cwd, plist: None)
    monkeypatch.setattr(_repos, "repo_key", lambda cwd: None)
    monkeypatch.setattr(_repos, "repo_name", lambda cwd, key: "")
    monkeypatch.setattr(_repos, "branch_of", lambda cwd: "")


def test_agent_tree_floats_awaiting_to_top_and_exposes_session_path(monkeypatch):
    """Une conversation qui attend une réponse de l'utilisateur remonte en haut.

    Même si elle est PLUS ANCIENNE qu'une conversation en cours d'exécution,
    la conversation 'awaiting_input' doit apparaître en premier — c'est là que
    l'utilisateur doit agir. On vérifie aussi que le chemin du JSON de session
    est exposé (pour le bouton copier / télécharger).
    """
    _patch_tree_deps(monkeypatch)
    running = _fake_agent("recent", started_at="2026-07-02T10:00:00",
                          session_path="/data/recent.json")
    awaiting = _fake_agent("old", started_at="2026-07-01T08:00:00",
                           session_path="/data/old.json")
    monkeypatch.setattr(agent_registre, "list_agents", lambda: [running, awaiting])

    meta = {
        "agent/recent": {"key": "agent/recent", "title": "recent",
                         "turn_count": 1,
                         "status": {"state": "running", "question": "",
                                    "options": [], "allow_freetext": True}},
        "agent/old": {"key": "agent/old", "title": "old", "turn_count": 5,
                      "status": {"state": "awaiting_input",
                                 "question": "Continuer ?", "options": [],
                                 "allow_freetext": True}},
    }
    monkeypatch.setattr(_store, "list_agent_sessions", lambda: list(meta.values()))

    tree = _fleet.agent_tree()
    nodes = tree["nodes"]

    assert nodes[0]["agent_id"] == "old"       # awaiting remonte EN HAUT
    assert nodes[0]["state"] == "awaiting_input"
    assert nodes[1]["agent_id"] == "recent"
    # (e) chemin de session exposé pour chaque node
    assert nodes[0]["session_path"] == "/data/old.json"
    assert nodes[1]["session_path"] == "/data/recent.json"


# ---------------------------------------------------------------------------
# (e) route de téléchargement du JSON de session
# ---------------------------------------------------------------------------
@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_download_session_json_returns_attachment(monkeypatch, client, tmp_path):
    """L'utilisateur peut télécharger le JSON brut d'une session en 1 clic."""
    from bouzecode.web_v2.routes import sessions as _routes
    session_file = tmp_path / "session_abc.json"
    session_file.write_text('{"first_message": "hello"}', encoding="utf-8")
    ref = _store.SessionRef(key="agent/abc", kind="agent", path=session_file)
    monkeypatch.setattr(_routes.store, "resolve", lambda key: ref)

    resp = client.get("/api/sessions/agent/abc/download")

    assert resp.status_code == 200
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert "session_abc.json" in disposition
    assert b"hello" in resp.data


def test_download_session_json_unknown_key_404(monkeypatch, client):
    """Clé de session inconnue → 404 propre (pas de chemin arbitraire servi)."""
    from bouzecode.web_v2.routes import sessions as _routes
    monkeypatch.setattr(_routes.store, "resolve", lambda key: None)

    resp = client.get("/api/sessions/agent/ghost/download")

    assert resp.status_code == 404
