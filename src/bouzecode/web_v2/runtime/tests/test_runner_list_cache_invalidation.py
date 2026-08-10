import time

from bouzecode.web_v2.runtime import runner


def _mk_agent(agent_id: str) -> runner.Agent:
    return runner.Agent(
        agent_id=agent_id,
        prompt="do stuff",
        model="sonnet",
        cwd="/tmp",
        pid=1234,
        started_at="2026-07-20T00:00:00Z",
        session_path=str(runner.AGENTS_DIR / f"{agent_id}.session.json"),
        ticket_id="T-flicker",
    )


def test_save_invalidates_list_agents_cache(tmp_path, monkeypatch):
    """Regression: a freshly-persisted agent must be visible on the very next
    list_agents() call, WITHOUT waiting for the TTL to expire.

    The flicker bug (ticket appears -> disappears -> reappears) came from
    _save() persisting the session while list_agents() kept serving a stale
    cache (TTL=3s) that did not include the new agent. During that window the
    ticket was neither in launching_tickets() (flag cleared by add_run) nor in
    the cached list_agents() nodes -> it vanished from one tree refresh.
    """
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)

    # Prime the cache with a NON-expired state that does NOT know the new agent.
    with runner._list_agents_lock:
        runner._list_agents_cache["data"] = []
        runner._list_agents_cache["expires"] = time.time() + 100

    # Persist a brand new agent (mirrors create_agent's final _save()).
    agent = _mk_agent("flicker01")
    runner._save(agent)

    # The cache must have been invalidated so the next list_agents() recomputes.
    with runner._list_agents_lock:
        expires = runner._list_agents_cache.get("expires")
    assert expires is None or expires <= time.time(), (
        "_save must invalidate the list_agents cache so a new agent is visible "
        "immediately (no TTL wait) — otherwise the tree flickers"
    )

    # And the recomputed list_agents() actually sees the new agent.
    ids = {a.agent_id for a in runner.list_agents()}
    assert "flicker01" in ids
