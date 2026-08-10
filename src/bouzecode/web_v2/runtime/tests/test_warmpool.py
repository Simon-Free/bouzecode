"""Unit tests for the warm-pool eviction policy (pure logic, no process spawn)."""
from datetime import datetime, timedelta, timezone

from bouzecode.web_v2.runtime.warmpool import decide_evictions


NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _node(agent_id, state="finished", warm=True, parent="", minutes_ago=0):
    return {
        "agent_id": agent_id,
        "parent": parent,
        "state": state,
        "warm": warm,
        "last_activity": _iso(NOW - timedelta(minutes=minutes_ago)),
    }


def test_ttl_evicts_inactive_warm_agent():
    nodes = [_node("a", state="finished", minutes_ago=16)]
    assert decide_evictions(nodes, NOW, max_pool=10) == ["a"]


def test_ttl_keeps_recently_active_warm_agent():
    nodes = [_node("a", state="finished", minutes_ago=5)]
    assert decide_evictions(nodes, NOW, max_pool=10) == []


def test_ttl_applies_even_to_running_but_running_is_fresh():
    # A genuinely running agent has a fresh last_activity → not evicted.
    nodes = [_node("a", state="running", minutes_ago=1)]
    assert decide_evictions(nodes, NOW, max_pool=10) == []


def test_ttl_hits_any_state_if_truly_inactive():
    # Literal reading: even a stale 'running' record past TTL is evicted.
    nodes = [_node("a", state="running", minutes_ago=20)]
    assert decide_evictions(nodes, NOW, max_pool=10) == ["a"]


def test_lru_pressure_evicts_only_terminated():
    # max_pool=1, three warm agents; one running (immune), two finished.
    nodes = [
        _node("run", state="running", minutes_ago=2),
        _node("old", state="finished", minutes_ago=10),
        _node("new", state="finished", minutes_ago=3),
    ]
    # 3 warm > max_pool 1 → overflow 2, but 'run' is immune → only terminated.
    # Terminated sorted LRU: old (10m) then new (3m). Overflow=2 → both evicted.
    assert decide_evictions(nodes, NOW, max_pool=1) == ["new", "old"]


def test_lru_pressure_never_evicts_running():
    nodes = [
        _node("run", state="running", minutes_ago=1),
        _node("fin", state="finished", minutes_ago=2),
    ]
    # 2 warm > max_pool 1 → overflow 1, only terminated candidate = fin.
    assert decide_evictions(nodes, NOW, max_pool=1) == ["fin"]


def test_parent_with_active_child_is_immune_under_pressure():
    nodes = [
        _node("parent", state="finished", minutes_ago=5),
        _node("child", state="running", parent="parent", minutes_ago=1),
        _node("other", state="finished", minutes_ago=8),
    ]
    # 3 warm > max_pool 1. 'parent' has an active descendant → immune.
    # 'child' is active → immune. Only 'other' is terminated-recursive → evicted.
    assert decide_evictions(nodes, NOW, max_pool=1) == ["other"]


def test_awaiting_input_never_evicted_under_pressure():
    nodes = [
        _node("wait", state="awaiting_input", minutes_ago=3),
        _node("fin", state="finished", minutes_ago=4),
    ]
    assert decide_evictions(nodes, NOW, max_pool=1) == ["fin"]


def test_non_warm_never_evicted():
    nodes = [_node("cold", state="finished", warm=False, minutes_ago=60)]
    assert decide_evictions(nodes, NOW, max_pool=1) == []


def test_no_pressure_no_eviction():
    nodes = [
        _node("a", state="finished", minutes_ago=3),
        _node("b", state="finished", minutes_ago=4),
    ]
    assert decide_evictions(nodes, NOW, max_pool=10) == []
