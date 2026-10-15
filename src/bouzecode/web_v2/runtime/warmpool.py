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
4. Unfinished work (`travail_en_cours`: open ticket, run ended without a delivery) is
   NEVER evicted: the process ends by itself after its own idle TTL (`ipc.run_agent_event_loop`),
   and killing it earlier only turned an idle agent into a « planté » ticket (2026-09-29).
5. UNKNOWN activity (missing or unparseable date) means « do not evict », never « infinitely
   old ». The former `_parse_ts("") -> epoch` made any agent without a readable date the first
   victim of both the TTL and the LRU.

Dates are compared as REAL instants normalised to UTC (`parse_instant`), never as strings:
`max()` over `"2026-09-29T08:12:34Z"` (spawn, UTC) and `"2026-09-29 10:58:52"` (session save,
local, space separator) picked the spawn date because 'T' > ' ', so a conversation started more
than 15 min earlier was evicted ~15 s after EVERY turn (c4e9964adb48, 21a97ffc1a95, 2026-09-29).

A parent is considered active as long as at least one descendant is active
(sub-agents keep their parent warm).
"""
from __future__ import annotations

from datetime import datetime

from bouzecode.web_v2.services.horodatage import lire_instant, maintenant

ACTIVE_STATES = {"running", "awaiting_input", "awaiting_plan_validation"}
DEFAULT_TTL_SECONDS = 900  # 15 minutes of INACTIVITY

#  `parent` d'une conversation lancée par un DISPATCHER (`dispatcher:manual` = depuis l'écran,
#  cf. `runner.MANUAL_PARENT`) : un sentinelle, pas une parenté. Le prendre pour un parent
#  appliquait la règle 0 aux SEULES conversations que la résidence existe pour servir.
_PREFIXE_DISPATCHER = "dispatcher:"

REGLE_SOUS_AGENT = "sous_agent_inactif"
REGLE_TTL = "ttl_inactivite"
REGLE_LRU = "lru_pool_plein"


def is_subagent(node: dict) -> bool:
    """Le nœud a-t-il un VRAI parent (un agent) ? Un sentinelle de dispatcher n'en est pas un."""
    parent = str(node.get("parent") or "")
    return bool(parent) and not parent.startswith(_PREFIXE_DISPATCHER)


def parse_instant(value) -> datetime | None:
    """Un instant UTC conscient, ou None : délègue à `horodatage.lire_instant` (naïf = LOCAL —
    c'est ainsi que le harnais écrit `saved_at` et qu'étaient écrites les anciennes dates de
    ticket ; tout le reste porte son fuseau)."""
    return lire_instant(value)


def latest_instant(values) -> datetime | None:
    """Le plus récent des instants LISIBLES de `values` (None si aucun ne l'est)."""
    instants = [i for i in (parse_instant(v) for v in values) if i is not None]
    return max(instants) if instants else None


def _active_predicate(nodes: list[dict]):
    """agent_id → actif (lui-même ou un descendant). Mémorisé, tolérant aux cycles."""
    by_id = {n["agent_id"]: n for n in nodes}
    children: dict[str, list[str]] = {n["agent_id"]: [] for n in nodes}
    for n in nodes:
        parent = n.get("parent") or ""
        if parent in children:
            children[parent].append(n["agent_id"])
    cache: dict[str, bool] = {}

    def active(agent_id: str) -> bool:
        if agent_id not in cache:
            cache[agent_id] = False  # en cours d'évaluation : casse un éventuel cycle
            node = by_id.get(agent_id)
            cache[agent_id] = node is not None and (
                node.get("state", "") in ACTIVE_STATES
                or any(active(child) for child in children[agent_id]))
        return cache[agent_id]

    return active


def _motif(regle: str, node: dict, now: datetime, ttl_seconds: int, **extra) -> dict:
    derniere = parse_instant(node.get("last_activity"))
    return {"regle": regle,
            "derniere_activite": derniere.isoformat() if derniere else "",
            "age_s": round((now - derniere).total_seconds(), 1) if derniere else None,
            "ttl_s": ttl_seconds, **extra}


def decide_evictions_motivees(
    nodes: list[dict],
    now: datetime,
    max_pool: int,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, dict]:
    """{agent_id: motif} des process chauds à évincer ; le motif dit QUELLE règle a joué et
    sur quelles dates (il part tel quel dans le journal des arrêts).

    Each node is a dict with keys: agent_id, parent ("" if root), state, warm (bool: a live
    idle process is kept), last_activity (ISO-8601 / datetime / epoch, "" if unknown), and
    optionally travail_en_cours (bool)."""
    now = parse_instant(now) or maintenant()
    active = _active_predicate(nodes)
    warm_nodes = [n for n in nodes if n.get("warm")]
    evict: dict[str, dict] = {}
    for n in warm_nodes:
        if n.get("travail_en_cours"):
            continue  # règle 4
        derniere = parse_instant(n.get("last_activity"))
        if is_subagent(n) and not active(n["agent_id"]):  # règle 0
            evict[n["agent_id"]] = _motif(REGLE_SOUS_AGENT, n, now, ttl_seconds)
        elif derniere is not None and (now - derniere).total_seconds() > ttl_seconds:  # règle 1
            evict[n["agent_id"]] = _motif(REGLE_TTL, n, now, ttl_seconds)
    still_warm = [n for n in warm_nodes if n["agent_id"] not in evict]
    overflow = len(still_warm) - max_pool
    if overflow > 0:  # règle 2, parmi les terminés dont l'activité est CONNUE (règle 5)
        candidates = [n for n in still_warm if not active(n["agent_id"])
                      and not n.get("travail_en_cours")
                      and parse_instant(n.get("last_activity")) is not None]
        candidates.sort(key=lambda n: parse_instant(n.get("last_activity")))
        for n in candidates[:overflow]:
            evict[n["agent_id"]] = _motif(REGLE_LRU, n, now, ttl_seconds,
                                          pool=len(still_warm), max_pool=max_pool)
    return evict


def decide_evictions(
    nodes: list[dict],
    now: datetime,
    max_pool: int,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> list[str]:
    """Return the sorted list of agent_ids whose warm process should be evicted."""
    return sorted(decide_evictions_motivees(nodes, now, max_pool, ttl_seconds))
