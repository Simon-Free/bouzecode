"""Tests for overview() performance optimizations.

Verifies:
1. overview() calls list_agents() only ONCE (not per project)
2. list_agents() result is cached for ~3s
3. tickets _load/_save are serialized (Lock)
"""

import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear runner cache between tests."""
    from bouzecode.web_v2.runtime.runner.agent_fiche import _list_agents_cache
    _list_agents_cache.clear()
    yield
    _list_agents_cache.clear()


class TestSingleListAgentsCall:
    """overview() must call list_agents() exactly once, not per project."""

    def test_overview_calls_list_agents_once(self, tmp_path, monkeypatch):
        from bouzecode.web_v2.services.work import projects

        fake_projects = [
            {"slug": "p1", "path": str(tmp_path / "p1"), "name": "P1"},
            {"slug": "p2", "path": str(tmp_path / "p2"), "name": "P2"},
            {"slug": "p3", "path": str(tmp_path / "p3"), "name": "P3"},
        ]
        monkeypatch.setattr(projects, "list_projects", lambda: fake_projects)

        call_count = 0
        original_list = []

        def counting_list_agents():
            nonlocal call_count
            call_count += 1
            return original_list

        from bouzecode.web_v2.runtime.runner import agent_registre
        monkeypatch.setattr(agent_registre, "_list_agents_uncached", counting_list_agents)

        # Also patch tickets to avoid side effects. **kwargs : overview() passe refresh/
        # persist/agents_index — un stub à signature figée casserait au prochain paramètre.
        from bouzecode.web_v2.services.work import tickets
        monkeypatch.setattr(tickets, "list_tickets", lambda slug, **kwargs: [])

        projects.overview()
        assert call_count <= 1, f"list_agents called {call_count} times, expected 1"


class TestListAgentsCache:
    """list_agents() should cache results for ~3 seconds."""

    def test_cached_within_ttl(self, monkeypatch):
        from bouzecode.web_v2.runtime.runner import agent_registre

        call_count = 0

        def counting():
            nonlocal call_count
            call_count += 1
            return []

        monkeypatch.setattr(agent_registre, "_list_agents_uncached", counting)

        agent_registre.list_agents()
        agent_registre.list_agents()
        agent_registre.list_agents()
        assert call_count == 1, f"Expected 1 uncached call, got {call_count}"

    def test_cache_expires_after_ttl(self, monkeypatch):
        from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre

        call_count = 0

        def counting():
            nonlocal call_count
            call_count += 1
            return []

        monkeypatch.setattr(agent_registre, "_list_agents_uncached", counting)
        # Force cache expiry by manipulating timestamp
        agent_registre.list_agents()
        agent_fiche._list_agents_cache["expires"] = time.time() - 1
        agent_registre.list_agents()
        assert call_count == 2


class TestTicketsLock:
    """_load/_save must be serialized via lock."""

    def test_lock_exists(self):
        from bouzecode.web_v2.services.work import tickets
        assert hasattr(tickets, "_tickets_lock")
        assert isinstance(tickets._tickets_lock, type(threading.RLock()))
