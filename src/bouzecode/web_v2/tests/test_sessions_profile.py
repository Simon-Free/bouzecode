import json

import pytest


def _make_agent(agent_id, profile, session_path):
    from bouzecode.web_v2.runtime.runner import Agent

    return Agent(
        agent_id=agent_id,
        prompt=f"prompt for {agent_id}",
        model="claude-sonnet",
        cwd="/tmp/work",
        pid=0,
        started_at="2026-06-30T10:00:00Z",
        finished_at="",
        returncode=None,
        session_path=str(session_path),
        profile=profile,
    )


@pytest.fixture()
def _fake_agents(tmp_path, monkeypatch):
    """Patch store to expose two web agents: one manager, one general-purpose."""
    from bouzecode.web_v2.services.sessions import store

    daily_dir = tmp_path / "daily"
    daily_dir.mkdir(parents=True)
    monkeypatch.setattr(store, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "cache.json")

    session_payload = {"model": "claude-sonnet", "messages": []}
    sess_mgr = tmp_path / "session_mgr.json"
    sess_gp = tmp_path / "session_gp.json"
    sess_mgr.write_text(json.dumps(session_payload), encoding="utf-8")
    sess_gp.write_text(json.dumps(session_payload), encoding="utf-8")

    agents = [
        _make_agent("mgr1", "manager", sess_mgr),
        _make_agent("gp1", "general-purpose", sess_gp),
    ]

    from bouzecode.web_v2.services.sessions.store import runner as _runner

    monkeypatch.setattr(_runner, "list_agents", lambda: agents)


@pytest.fixture()
def client(_fake_agents):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_sessions_expose_profile_and_typology(client):
    response = client.get("/api/sessions")
    assert response.status_code == 200
    data = response.get_json()

    agents = data["agents"]
    assert len(agents) == 2, agents

    # Every agent entry MUST expose profile AND typology.
    for agent in agents:
        assert "profile" in agent, agent
        assert "typology" in agent, agent

    by_key = {a["key"]: a for a in agents}
    mgr = by_key["agent/mgr1"]
    gp = by_key["agent/gp1"]

    assert mgr["profile"] == "manager"
    assert mgr["typology"] == "manager"
    assert gp["profile"] == "general-purpose"
    assert gp["typology"] == "general-purpose"
