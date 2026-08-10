"""Pure-logic tests for the /agent-upgrade plugin selection."""
from __future__ import annotations

from bouzecode.backend.commands.agent_upgrade import _plugins_to_upgrade
from bouzecode.backend.profiles.models import AgentProfile


def _profiles():
    return {
        "alpha": AgentProfile(
            name="alpha",
            requires_plugins=["pkg-a", {"name": "pkg-b", "source": "git+https://x/b"}],
        ),
        "beta": AgentProfile(
            name="beta",
            requires_plugins=[{"package": "pkg-a"}, "pkg-c"],
        ),
    }


def test_all_profiles_dedup_by_package():
    plugins, err = _plugins_to_upgrade(_profiles(), None)
    assert err is None
    packages = [p["package"] for p in plugins]
    assert packages.count("pkg-a") == 1
    assert set(packages) == {"pkg-a", "pkg-b", "pkg-c"}
    by_pkg = {p["package"]: p["source"] for p in plugins}
    assert by_pkg["pkg-b"] == "git+https://x/b"
    assert by_pkg["pkg-a"] is None


def test_single_agent_selection():
    plugins, err = _plugins_to_upgrade(_profiles(), "alpha")
    assert err is None
    assert {p["package"] for p in plugins} == {"pkg-a", "pkg-b"}


def test_unknown_agent_returns_error_with_available_names():
    plugins, err = _plugins_to_upgrade(_profiles(), "ghost")
    assert plugins == []
    assert err is not None
    assert "ghost" in err
    assert "alpha" in err and "beta" in err
