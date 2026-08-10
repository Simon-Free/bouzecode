"""Tests for the agent catalog UI API (/api/agents/catalog, /install, /refresh)."""
from __future__ import annotations

import pytest

from bouzecode.backend.core import config as core_config
from bouzecode.backend.profiles.models import AgentProfile
from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services import agent_catalog


def _profile(name: str, requires=None) -> AgentProfile:
    return AgentProfile(
        name=name,
        tools=["Read", "Write"],
        skills=[],
        hooks=[],
        requires_plugins=list(requires or []),
        model=None,
        system_prompt_extra=f"Prompt for {name}",
    )


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(core_config, "CONFIG_DIR", tmp_path, raising=False)
    monkeypatch.setattr(core_config, "CONFIG_FILE", tmp_path / "config.json", raising=False)
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)


@pytest.fixture
def fake_catalog(monkeypatch):
    installed = {"inst-agent": _profile("inst-agent")}
    available = {"avail-agent": _profile("avail-agent", requires=["some-plugin"])}
    all_profiles = {**installed, **available}

    monkeypatch.setattr(
        agent_catalog.catalog, "installed_and_available",
        lambda: (installed, available),
    )
    monkeypatch.setattr(
        agent_catalog.catalog, "list_catalog_profiles",
        lambda: all_profiles,
    )
    refreshed = {"called": False}
    monkeypatch.setattr(
        agent_catalog.catalog, "refresh_catalog",
        lambda force=False: refreshed.__setitem__("called", True),
    )
    monkeypatch.setattr(
        agent_catalog.plugin_resolver, "ensure_plugins",
        lambda requires: ([], []),
    )
    return {"installed": installed, "available": available, "refreshed": refreshed}


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_catalog_lists_installed_and_available(client, fake_catalog):
    resp = client.get("/api/agents/catalog")
    assert resp.status_code == 200
    data = resp.get_json()
    inst_names = {a["name"] for a in data["installed"]}
    avail_names = {a["name"] for a in data["available"]}
    assert "inst-agent" in inst_names
    assert "avail-agent" in avail_names
    # entries expose name + tools.
    avail = next(a for a in data["available"] if a["name"] == "avail-agent")
    assert "Read" in avail["tools"]


def test_install_writes_profile_and_ok(client, fake_catalog):
    resp = client.post("/api/agents/install", json={"name": "avail-agent"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["errors"] == []
    dest = core_config.CONFIG_DIR / "profiles" / "avail-agent.yaml"
    assert dest.exists()


def test_install_unknown_agent_returns_error(client, fake_catalog):
    resp = client.post("/api/agents/install", json={"name": "ghost"})
    data = resp.get_json()
    assert data["ok"] is False
    assert data["errors"]


def test_install_surfaces_plugin_errors(client, fake_catalog, monkeypatch):
    monkeypatch.setattr(
        agent_catalog.plugin_resolver, "ensure_plugins",
        lambda requires: ([], ["plugin boom: unreachable"]),
    )
    resp = client.post("/api/agents/install", json={"name": "avail-agent"})
    data = resp.get_json()
    assert data["ok"] is False
    assert any("boom" in e for e in data["errors"])


def test_refresh_calls_refresh_catalog(client, fake_catalog):
    resp = client.post("/api/agents/catalog/refresh")
    assert resp.status_code == 200
    assert fake_catalog["refreshed"]["called"] is True
    data = resp.get_json()
    assert "installed" in data and "available" in data
