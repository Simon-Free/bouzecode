"""Tests for 2 production web fixes (2026-06-10):
1. Environment guard at agent spawn
2. awaiting_plan_validation state in store

(Un 3e point — `paralysis_abort_after` pilotable depuis l'API web — a été retiré le
2026-07-29 en même temps que le levier, qui n'avait aucun consommateur.)
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime.runner import agent_fiche
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.agent_fiche.AGENTS_DIR", agents_dir)
    # list_agents keeps a module-global TTL cache not keyed by AGENTS_DIR — clear it
    # so a prior test's agents don't leak into this isolated dir.
    agent_fiche._list_agents_cache.clear()
    return agents_dir


@pytest.fixture()
def fake_agent(tmp_agents_dir):
    """Create a minimal agent JSON on disk."""
    agent_id = uuid.uuid4().hex[:12]
    ipc_dir = tmp_agents_dir / f"{agent_id}.ipc"
    ipc_dir.mkdir()
    session_path = tmp_agents_dir / f"{agent_id}.session.json"
    session_path.write_text("[]", encoding="utf-8")
    data = {
        "agent_id": agent_id,
        "prompt": "test",
        "model": "claude-sonnet-4-5",
        "cwd": str(tmp_agents_dir),
        "pid": 99999,
        "started_at": "2026-06-10T10:00:00Z",
        "stdout_path": str(tmp_agents_dir / f"{agent_id}.out.log"),
        "session_path": str(session_path),
        "ipc_dir": str(ipc_dir),
    }
    path = tmp_agents_dir / f"{agent_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return data, ipc_dir


# ---------------------------------------------------------------------------
# Point 1 SUPPRIMÉ le 2026-07-29 avec le levier lui-même.
#
# `TestParalysisAbortAfter` vérifiait que l'API web propageait `paralysis_abort_after`
# jusqu'à BOUZECODE_PARALYSIS_ABORT_AFTER dans l'environnement du sous-process. Tout
# était vrai, et parfaitement inutile : `_get_paralysis_abort_after()` n'avait AUCUN
# appelant dans src/. La chaîne était donc verte de bout en bout — paramètre d'API,
# route, runner, variable d'environnement — et n'aboutissait à rien.
#
# C'est le mode d'échec le plus coûteux d'une suite de tests : des tests qui passent en
# épinglant le TRANSPORT d'une valeur, sans que rien ne prouve que quelqu'un la lise.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Point 2: Environment guard
# ---------------------------------------------------------------------------

class TestEnvGuard:
    """runner.check_provider_env raises on missing env."""

    def test_anthropic_missing_base_url(self, monkeypatch):
        from bouzecode.web_v2.runtime.runner.agent_commande import (
            check_provider_env,
            MissingProviderEnvError,
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        with pytest.raises(MissingProviderEnvError, match="ANTHROPIC_BASE_URL"):
            check_provider_env("claude-sonnet-4-5")

    def test_anthropic_missing_api_key(self, monkeypatch):
        from bouzecode.web_v2.runtime.runner.agent_commande import (
            check_provider_env,
            MissingProviderEnvError,
        )
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
        with pytest.raises(MissingProviderEnvError, match="ANTHROPIC_API_KEY"):
            check_provider_env("claude-sonnet-4-5")

    def test_openrouter_missing_key(self, monkeypatch):
        from bouzecode.web_v2.runtime.runner.agent_commande import (
            check_provider_env,
            MissingProviderEnvError,
        )
        monkeypatch.delenv("OPENROUTER_KEY", raising=False)
        with pytest.raises(MissingProviderEnvError, match="OPENROUTER_KEY"):
            check_provider_env("deepseek-v4-flash")

    def test_anthropic_ok(self, monkeypatch):
        from bouzecode.web_v2.runtime.runner.agent_commande import check_provider_env
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
        # Should not raise
        check_provider_env("claude-sonnet-4-5")

    def test_create_agent_fails_on_missing_env(self, monkeypatch, tmp_agents_dir):
        """create_agent raises MissingProviderEnvError instead of spawning."""
        from bouzecode.web_v2.runtime.runner.agent_commande import MissingProviderEnvError
        from bouzecode.web_v2.runtime.runner import agent_creation

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        with pytest.raises(MissingProviderEnvError):
            agent_creation.create_agent("hello", "claude-sonnet-4-5", str(tmp_agents_dir))


# ---------------------------------------------------------------------------
# Point 3: awaiting_plan_validation state
# ---------------------------------------------------------------------------

class TestAwaitingPlanValidation:
    """store.agent_status returns 'awaiting_plan_validation' when IPC says so."""

    def test_state_awaiting_plan_validation(self, monkeypatch, fake_agent):
        from bouzecode.web_v2.services.sessions import store
        from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche, agent_vivacite

        agent_data, ipc_dir = fake_agent
        agent = agent_fiche._agent_from_dict(agent_data)

        # Mock refresh to not check real PID
        monkeypatch.setattr(agent_etat, "refresh_agent_status", lambda a: a)
        monkeypatch.setattr(agent_vivacite, "is_running", lambda a: False)
        monkeypatch.setattr(agent_etat, "get_ipc_state", lambda a: {
            "status": "awaiting_plan_validation",
            "question": "Validate plan?",
            "options": [{"label": "approve"}, {"label": "reject"}],
        })

        result = store.agent_status(agent)
        assert result["state"] == "awaiting_plan_validation"
        assert result["question"] == "Validate plan?"

    def test_state_finished_when_done(self, monkeypatch, fake_agent):
        from bouzecode.web_v2.services.sessions import store
        from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche, agent_vivacite

        agent_data, ipc_dir = fake_agent
        agent = agent_fiche._agent_from_dict(agent_data)

        monkeypatch.setattr(agent_etat, "refresh_agent_status", lambda a: a)
        monkeypatch.setattr(agent_vivacite, "is_running", lambda a: False)
        monkeypatch.setattr(agent_etat, "get_ipc_state", lambda a: {"status": "finished"})

        result = store.agent_status(agent)
        assert result["state"] == "finished"
