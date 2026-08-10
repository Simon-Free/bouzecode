# [desc] Agent export/import + plugin list API: round-trip a profile and list installed plugins via the web layer. [/desc]
"""Isolated via tmp CONFIG_DIR — no mocking lib, no real ~/.bouzecode, no real pip."""
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from bouzecode.backend.core import config, paths
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    paths.register_extra_dirs([])
    yield
    paths.register_extra_dirs([])


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_export_then_import_round_trips_profile(client):
    body = {
        "name": "demo-explorer", "tools": ["Read", "Grep"],
        "requires_plugins": [], "system_prompt_extra": "Explore la base de demo.",
    }
    assert client.post("/api/profiles", json=body).status_code == 200

    exported = client.get("/api/agents/demo-explorer/export").get_json()
    assert exported["name"] == "demo-explorer"
    assert "requires_plugins" in exported["yaml"]

    # Delete then re-import from the exported YAML
    client.delete("/api/profiles/demo-explorer")
    result = client.post("/api/agents/import", json={"yaml": exported["yaml"]}).get_json()
    assert result["name"] == "demo-explorer"
    assert result["errors"] == []

    reloaded = client.get("/api/profiles/demo-explorer").get_json()
    assert reloaded["tools"] == ["Read", "Grep"]


def test_export_unknown_agent_404(client):
    assert client.get("/api/agents/nope/export").status_code == 404


def test_import_invalid_yaml_400(client):
    resp = client.post("/api/agents/import", json={"yaml": "not a mapping"})
    assert resp.status_code == 400


def test_plugins_list_is_empty_when_none_installed(client):
    data = client.get("/api/plugins").get_json()
    assert data["plugins"] == []


_GIT_AGENT = (
    "name: git-agent\n"
    "requires_plugins:\n"
    "  - name: my-plugin\n"
    "    source: git+https://example.com/x/my-plugin.git\n"
)


def test_import_git_source_requires_confirmation_and_does_not_save(client):
    resp = client.post("/api/agents/import", json={"yaml": _GIT_AGENT})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["requires_confirmation"] is True
    assert any("git+https://" in s for s in body["git_sources"])
    # NOT saved yet: the profile must not exist
    assert client.get("/api/profiles/git-agent").status_code == 404


def test_install_plugin_git_source_requires_confirmation(client):
    resp = client.post("/api/plugins", json={
        "package": "my-plugin",
        "source": "git+https://example.com/x/my-plugin.git",
    })
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["requires_confirmation"] is True
    assert body["source"].startswith("git+https://")

