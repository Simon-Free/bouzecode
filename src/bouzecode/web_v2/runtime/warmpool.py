"""Warm-pool eviction policy (pure decision logic, no I/O, no process spawn).

A "warm" agent is a live child process kept idle after a turn so a follow-up
message can reuse it (no cold-start respawn). This module decides WHICH warm
agents to evict (kill the live process — the on-disk session stays resumable
via a cold respawn). It is intentionally pure so it can be unit-tested without
spawning any process.

Rules (locked with the user):
0. Sub-agents are NOT kept warm. The quarter-hour of residency exists to give the
   USER time to come back to their conversation; a sub-agent has no user — only its
   manager could write to it, and rarely. A warm sub-agent is therefore evicted as
   soon as it stops being active, without waiting for the TTL. Twelve sub-agents of
   one manager held twelve processes AND twelve warm-pool slots, at the expense of
   the conversations someone will actually return to.
1. Absolute inactivity TTL: any warm agent inactive for more than `ttl_seconds`
   is evicted, whatever its state. A genuinely active agent keeps a fresh
   `last_activity`, so in practice it is not touched.
2. LRU under pressure: when the number of warm agents exceeds `max_pool`, evict
   the least-recently-active agents — but ONLY among terminated ones — until the
   count is back to `max_pool`.
3. Immunity: an agent that is active (running / awaiting_input) OR has any
   active descendant is NEVER evicted by pressure (only the absolute TTL can
   reach it, and only once it has actually gone inactive).

A parent is considered active as long as at least one descendant is active
(sub-agents keep their parent warm).
"""
from __future__ import annotations

from datetime import datetime, timezone

ACTIVE_STATES = {"running", "awaiting_input", "awaiting_plan_validation"}
DEFAULT_TTL_SECONDS = 900  # 15 minutes of INACTIVITY


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (tolerates a trailing 'Z'). Naive → assume UTC."""
    if not value:
        # No activity timestamp → treat as epoch (maximally stale).
        return datetime.min.replace(tzinfo=timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _as_utc(now: datetime) -> datetime:
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now


def decide_evictions(
    nodes: list[dict],
    now: datetime,
    max_pool: int,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> list[str]:
    """Return the list of agent_ids whose warm process should be evicted.

    Each node is a dict with keys:
      - agent_id (str)
      - parent (str; "" if root)
      - state (str)
      - warm (bool; True iff a live idle process is being kept)
      - last_activity (ISO-8601 str)
    """
    now = _as_utc(now)
    by_id = {n["agent_id"]: n for n in nodes}
    children: dict[str, list[str]] = {n["agent_id"]: [] for n in nodes}
    for n in nodes:
        parent = n.get("parent") or ""
        if parent in children:
            children[parent].append(n["agent_id"])

    def active_self(node: dict) -> bool:
        return node.get("state", "") in ACTIVE_STATES

    _active_cache: dict[str, bool] = {}

    def active_recursive(agent_id: str) -> bool:
        if agent_id in _active_cache:
            return _active_cache[agent_id]
        node = by_id.get(agent_id)
        if node is None:
            _active_cache[agent_id] = False
            return False
        # Guard against cycles by marking in-progress as non-active first.
        _active_cache[agent_id] = False
        result = active_self(node) or any(
            active_recursive(child) for child in children.get(agent_id, [])
        )
        _active_cache[agent_id] = result
        return result

    warm_nodes = [n for n in nodes if n.get("warm")]
    evict: set[str] = set()

    # Rule 0 — a sub-agent is never held warm once it stops being active. `active_recursive`
    # (not `active_self`) so a sub-manager whose own children still work keeps its process:
    # it is the parent of someone active, and killing it would orphan a live sub-tree.
    for n in warm_nodes:
        if (n.get("parent") or "") and not active_recursive(n["agent_id"]):
            evict.add(n["agent_id"])

    # Rule 1 — absolute inactivity TTL.
    for n in warm_nodes:
        inactivity = (now - _parse_ts(n.get("last_activity", ""))).total_seconds()
        if inactivity > ttl_seconds:
            evict.add(n["agent_id"])

    # Rule 2 — LRU under pressure, among TERMINATED (non-active-recursive) only.
    still_warm = [n for n in warm_nodes if n["agent_id"] not in evict]
    if len(still_warm) > max_pool:
        terminated = [
            n for n in still_warm if not active_recursive(n["agent_id"])
        ]
        # Least-recently-active first.
        terminated.sort(key=lambda n: _parse_ts(n.get("last_activity", "")))
        overflow = len(still_warm) - max_pool
        for n in terminated[:overflow]:
            evict.add(n["agent_id"])

    return sorted(evict)
