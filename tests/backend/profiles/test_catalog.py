"""Tests for the remote agent catalog backend."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.profiles import catalog
from bouzecode.backend.profiles.models import AgentProfile


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _make_remote_repo(tmp_path: Path) -> Path:
    """Build a real git repo with two agent profiles and one commit."""
    repo = tmp_path / "demo_agents"
    profiles = repo / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "installed_agent.yaml").write_text(
        "name: installed_agent\n"
        "tools: [Read, Edit]\n"
        "requires_plugins: [mypkg]\n",
        encoding="utf-8",
    )
    (profiles / "free_agent.yaml").write_text(
        "name: free_agent\n"
        "tools: [Read]\n",
        encoding="utf-8",
    )
    _git(["init"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)
    _git(["add", "."], repo)
    _git(["commit", "-m", "initial"], repo)
    return repo


class _FakeEntry:
    def __init__(self, name, package):
        self.name = name
        self.package = package


@pytest.fixture
def catalog_env(tmp_path, monkeypatch):
    """Point the catalog at a local file:// repo and an isolated cache dir."""
    remote = _make_remote_repo(tmp_path)
    cache = tmp_path / "agent_catalog"
    monkeypatch.setattr(catalog, "CATALOG_DIR", cache)
    monkeypatch.setenv(catalog._ENV_URL, remote.as_uri())
    # No local user profiles by default (isolate the split logic).
    monkeypatch.setattr(catalog.discovery, "load_user_profiles", dict)
    return {"remote": remote, "cache": cache}


def test_refresh_clone_then_split(catalog_env, monkeypatch):
    # mypkg is installed -> installed_agent counts as installed.
    monkeypatch.setattr(
        catalog.store, "list_plugins",
        lambda *a, **k: [_FakeEntry("mypkg", "mypkg")],
    )
    catalog.refresh_catalog()
    assert (catalog_env["cache"] / "profiles" / "installed_agent.yaml").is_file()

    profiles = catalog.list_catalog_profiles()
    assert set(profiles) == {"installed_agent", "free_agent"}

    installed, available = catalog.installed_and_available()
    assert "installed_agent" in installed
    assert "free_agent" in installed  # no requires_plugins => installed
    assert available == {}


def test_split_when_plugin_missing(catalog_env, monkeypatch):
    monkeypatch.setattr(catalog.store, "list_plugins", lambda *a, **k: [])
    catalog.refresh_catalog()
    installed, available = catalog.installed_and_available()
    assert "free_agent" in installed  # no requires => installed
    assert "installed_agent" in available  # mypkg missing
    assert "installed_agent" not in installed


def test_local_profiles_always_installed(catalog_env, monkeypatch):
    monkeypatch.setattr(catalog.store, "list_plugins", lambda *a, **k: [])
    local = AgentProfile(name="local_only", tools=["Read"])
    monkeypatch.setattr(
        catalog.discovery, "load_user_profiles",
        lambda: {"local_only": local},
    )
    catalog.refresh_catalog()
    installed, available = catalog.installed_and_available()
    assert "local_only" in installed
    assert "local_only" not in available


def test_refresh_idempotent_pull(catalog_env):
    catalog.refresh_catalog()
    # Second call hits the git pull --ff-only branch, must not raise.
    result = catalog.refresh_catalog()
    assert result == catalog_env["cache"]
    profiles = catalog.list_catalog_profiles()
    assert set(profiles) == {"installed_agent", "free_agent"}


def _config(monkeypatch, **values):
    monkeypatch.setattr(
        "bouzecode.backend.core.config.load_config", lambda: values, raising=False,
    )


def test_url_resolution_errors_when_unset(monkeypatch):
    """Nothing is hardcoded: with no explicit URL and no git base, it must fail loud."""
    monkeypatch.delenv(catalog._ENV_URL, raising=False)
    monkeypatch.delenv(catalog._ENV_CATALOG_PATH, raising=False)
    _config(monkeypatch)
    with pytest.raises(RuntimeError):
        catalog._catalog_url()


def test_explicit_url_wins(monkeypatch):
    monkeypatch.setenv(catalog._ENV_URL, "https://git.example.com/me/agents.git")
    _config(monkeypatch, gitlab_url="https://other.example.com")
    assert catalog._catalog_url() == "https://git.example.com/me/agents.git"


def test_url_derived_from_configured_git_base(monkeypatch):
    monkeypatch.delenv(catalog._ENV_URL, raising=False)
    monkeypatch.setenv(catalog._ENV_CATALOG_PATH, "/myorg/agents.git")
    _config(monkeypatch, gitlab_url="https://gitlab.example.com/")
    assert catalog._catalog_url() == "https://gitlab.example.com/myorg/agents.git"
