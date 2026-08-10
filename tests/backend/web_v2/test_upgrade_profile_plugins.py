"""Branch tests for upgrade_profile_plugins (no network, no mock).

We swap load_user_profiles on the module for a lambda returning fake profile
objects. Only the side-effect-free branches are exercised:
  (a) unknown agent -> {"error": ...}
  (b) git source + confirm_git=False -> {"requires_confirmation": True, sources}
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services import plugins as plugins_svc


class _FakeProfile:
    def __init__(self, requires_plugins):
        self.requires_plugins = requires_plugins


@pytest.fixture
def fake_profiles(monkeypatch):
    def _set(profiles: dict):
        monkeypatch.setattr(plugins_svc, "load_user_profiles", lambda: profiles)
    return _set


def test_unknown_agent_returns_error(fake_profiles):
    fake_profiles({"alpha": _FakeProfile([])})
    result = plugins_svc.upgrade_profile_plugins("does-not-exist")
    assert "error" in result
    assert "does-not-exist" in result["error"]


def test_git_source_requires_confirmation(fake_profiles):
    profile = _FakeProfile([
        {"name": "my-plugin", "source": "https://github.com/acme/my-plugin.git"},
    ])
    fake_profiles({"alpha": profile})
    result = plugins_svc.upgrade_profile_plugins("alpha", confirm_git=False)
    assert result.get("requires_confirmation") is True
    assert result["sources"]
    assert "github.com/acme/my-plugin.git" in result["sources"][0]
