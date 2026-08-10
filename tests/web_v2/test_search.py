# [desc] User-centric pytest suite for /api/search: validates keyword matching, AND, case, scope on real sessions. [/desc]
"""User-centric tests for the /api/search backend logic.

We exercise ``search_agents`` directly with real session files on disk and a
monkeypatched AGENTS_DIR + project/ticket store (no unittest.mock).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services import search as search_mod
from bouzecode.web_v2.services.work import projects as projects_mod
from bouzecode.web_v2.services.work import tickets as tickets_mod


def _write_session(agents_dir: Path, agent_id: str, *, user: str = "", final: str = "") -> None:
    """Write a realistic <id>.session.json with a user message + a FinalAnswer."""
    messages: list[dict] = []
    if user:
        messages.append({"role": "user", "content": user})
    if final:
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": "FinalAnswer", "input": {"answer": final}}],
        })
    path = agents_dir / f"{agent_id}.session.json"
    path.write_text(json.dumps({"messages": messages}), encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """AGENTS_DIR + a single open project/ticket referencing two agents."""
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)

    def fake_list_projects():
        return [{"slug": "proj-a"}]

    def fake_list_tickets(slug, refresh=False, done_agent="", persist=True,
                          include_archived=False):
        if slug != "proj-a":
            return []
        return [{
            "id": "tick-1",
            "title": "Ticket about bananas",
            "runs": [
                {"agent_id": "agent-user"},
                {"agent_id": "agent-final"},
            ],
        }]

    monkeypatch.setattr(projects_mod, "list_projects", fake_list_projects)
    monkeypatch.setattr(tickets_mod, "list_tickets", fake_list_tickets)
    return agents_dir


def test_match_in_user_message(env):
    _write_session(env, "agent-user", user="I talked about the migration plan today")
    _write_session(env, "agent-final", final="nothing relevant here")

    results = search_mod.search_agents("migration", scope="open")

    assert len(results) == 1
    res = results[0]
    assert res["agent_id"] == "agent-user"
    assert res["key"] == "agent/agent-user"
    assert res["ticket_slug"] == "proj-a"
    assert res["ticket_id"] == "tick-1"
    assert res["ticket_title"] == "Ticket about bananas"
    assert res["matches"][0]["role"] == "user"
    assert "migration" in res["matches"][0]["snippet"].casefold()


def test_match_in_final_answer(env):
    _write_session(env, "agent-user", user="hello world")
    _write_session(env, "agent-final", final="The deployment succeeded on the staging cluster")

    results = search_mod.search_agents("deployment", scope="open")

    assert len(results) == 1
    assert results[0]["agent_id"] == "agent-final"
    assert results[0]["matches"][0]["role"] == "final_answer"


def test_and_multi_word_requires_all(env):
    _write_session(env, "agent-user", user="the migration plan is ready")
    _write_session(env, "agent-final", final="unrelated content")

    # both words present -> match
    assert len(search_mod.search_agents("migration plan", scope="open")) == 1
    # one word missing -> no match
    assert search_mod.search_agents("migration rollback", scope="open") == []


def test_case_insensitive(env):
    _write_session(env, "agent-user", user="Discussing the DATABASE schema")
    _write_session(env, "agent-final", final="x")

    results = search_mod.search_agents("database", scope="open")
    assert len(results) == 1
    assert results[0]["agent_id"] == "agent-user"


def test_scope_all_includes_untracked_sessions(env):
    # session not referenced by any ticket
    _write_session(env, "orphan-agent", user="the orphan mentions kubernetes")
    _write_session(env, "agent-user", user="no keyword here")
    _write_session(env, "agent-final", final="none")

    # open scope only scans ticket-referenced agents -> orphan invisible
    assert search_mod.search_agents("kubernetes", scope="open") == []

    # all scope scans every session on disk
    results = search_mod.search_agents("kubernetes", scope="all")
    ids = {r["agent_id"] for r in results}
    assert "orphan-agent" in ids
    orphan = next(r for r in results if r["agent_id"] == "orphan-agent")
    assert orphan["ticket_slug"] is None  # best-effort, no ticket


def test_unreadable_session_is_ignored(env):
    _write_session(env, "agent-user", user="valid keyword content")
    # corrupt JSON for the other agent
    (env / "agent-final.session.json").write_text("{ this is not json", encoding="utf-8")

    # must not raise, and returns the valid match only
    results = search_mod.search_agents("keyword", scope="all")
    ids = {r["agent_id"] for r in results}
    assert "agent-user" in ids
    assert "agent-final" not in ids


def test_empty_query_returns_empty(env):
    _write_session(env, "agent-user", user="anything")
    assert search_mod.search_agents("", scope="open") == []
    assert search_mod.search_agents("   ", scope="open") == []
