# [desc] Scans saved session files to compute aggregate token usage and cost statistics for a dashboard. [/desc]
"""Scan saved sessions and compute aggregate token / cost statistics."""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from bouzecode.backend.agent.providers.registry import calc_cost

_DEFAULT_MODEL = "claude-opus-4-6"
_log = logging.getLogger(__name__)


# Anthropic usage semantics: `input_tokens` is the FULL prompt size —
# `cache_read_tokens` and `cache_creation_tokens` are SUBSETS of it.
# So: fresh_input = input_tokens - cache_read - cache_creation.
#
# Billing: fresh @ 1x, cache write @ 1.25x, cache read @ 0.1x.


@dataclass
class SessionRow:
    session_id: str
    saved_at: str
    date: str
    first_message: str
    turn_count: int
    user_loop_count: int
    input_tokens: int          # full prompt size (includes cache read + write)
    output_tokens: int
    cache_read_tokens: int     # portion served from cache (cheap)
    cache_write_tokens: int    # portion newly written to cache (small premium)
    cost: float
    model: str = ""
    tool_call_count: int = 0
    file_path: str = ""

    @property
    def tool_loop_count(self) -> int:
        return self.turn_count - self.user_loop_count

    @property
    def fresh_input_tokens(self) -> int:
        """Pure non-cached prompt tokens (billed at the regular 1x rate)."""
        return self.input_tokens


def _safe_median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


@dataclass
class DayRow:
    date: str
    sessions: int = 0
    turns: int = 0
    user_loops: int = 0
    tool_loops: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0
    avg_cost: float = 0.0
    median_cost: float = 0.0
    avg_tokens: float = 0.0
    median_tokens: float = 0.0

    @property
    def fresh_input_tokens(self) -> int:
        return self.input_tokens


@dataclass
class DashboardData:
    total_sessions: int = 0
    total_turns: int = 0
    total_user_loops: int = 0
    total_tool_loops: int = 0
    total_tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_cost: float = 0.0
    sessions: list[SessionRow] = field(default_factory=list)
    days: list[DayRow] = field(default_factory=list)

    @property
    def total_fresh_input_tokens(self) -> int:
        return self.total_input_tokens

    @property
    def cache_hit_ratio(self) -> float:
        """Fraction of prompt tokens served from cache. 0 if no input."""
        return (self.total_cache_read_tokens / self.total_input_tokens) if self.total_input_tokens else 0.0


def _count_tool_calls(data: dict) -> int:
    """Count total tool calls: prefer saved metadata, fall back to message scan."""
    stored = data.get("total_tool_calls")
    if stored is not None:
        return int(stored)
    return sum(
        len(m.get("tool_calls", []))
        for m in data.get("messages", [])
        if m.get("role") == "assistant"
    )


def _row_to_dict(row: SessionRow) -> dict:
    return {
        "session_id": row.session_id,
        "saved_at": row.saved_at,
        "date": row.date,
        "first_message": row.first_message,
        "turn_count": row.turn_count,
        "user_loop_count": row.user_loop_count,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "cache_write_tokens": row.cache_write_tokens,
        "cost": row.cost,
        "model": row.model,
        "tool_call_count": row.tool_call_count,
        "file_path": row.file_path,
    }


def _dict_to_row(d: dict) -> SessionRow:
    return SessionRow(
        session_id=d["session_id"],
        saved_at=d["saved_at"],
        date=d["date"],
        first_message=d["first_message"],
        turn_count=d["turn_count"],
        user_loop_count=d["user_loop_count"],
        input_tokens=d["input_tokens"],
        output_tokens=d["output_tokens"],
        cache_read_tokens=d["cache_read_tokens"],
        cache_write_tokens=d["cache_write_tokens"],
        cost=d["cost"],
        model=d.get("model", ""),
        tool_call_count=d.get("tool_call_count", 0),
        file_path=d.get("file_path", ""),
    )


def _parse_session(data: dict) -> SessionRow | None:
    sid = data.get("session_id", "")
    if not sid:
        return None
    saved = data.get("saved_at", "")
    date = saved[:10] if len(saved) >= 10 else ""
    in_tok = data.get("total_input_tokens", 0) or 0
    out_tok = data.get("total_output_tokens", 0) or 0
    cache_r = data.get("total_cache_read_tokens", 0) or 0
    cache_w = data.get("total_cache_creation_tokens", 0) or 0
    model = data.get("model") or _DEFAULT_MODEL
    return SessionRow(
        session_id=sid,
        saved_at=saved,
        date=date,
        first_message=data.get("first_message", ""),
        turn_count=data.get("turn_count", 0) or 0,
        user_loop_count=data.get("user_loop_count", 0) or 0,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cache_r,
        cache_write_tokens=cache_w,
        cost=calc_cost(model, in_tok, out_tok, cache_r, cache_w),
        model=model,
        tool_call_count=_count_tool_calls(data),
    )


def _load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            _log.debug("Dashboard cache corrupted, rebuilding")
    return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    try:
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception:
        _log.debug("Failed to write dashboard cache", exc_info=True)


def get_dashboard_data() -> DashboardData:
    from bouzecode.backend.core.config import DAILY_DIR

    cache_path = DAILY_DIR.parent / ".dashboard_cache.json"
    cache = _load_cache(cache_path)
    cache_dirty = False

    seen_ids: set[str] = set()
    rows: list[SessionRow] = []

    if DAILY_DIR.exists():
        for day_dir in sorted(DAILY_DIR.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue
            for fp in sorted(day_dir.glob("session_*.json"), reverse=True):
                fp_key = str(fp)
                try:
                    mtime = fp.stat().st_mtime
                except OSError:
                    continue

                cached_entry = cache.get(fp_key)
                if cached_entry and cached_entry.get("mtime") == mtime:
                    row = _dict_to_row(cached_entry["row"])
                else:
                    try:
                        data = json.loads(fp.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    row = _parse_session(data)
                    if row:
                        cache[fp_key] = {"mtime": mtime, "row": _row_to_dict(row)}
                        cache_dirty = True

                if row and row.session_id not in seen_ids:
                    row.file_path = str(fp)
                    seen_ids.add(row.session_id)
                    rows.append(row)

    if cache_dirty:
        _save_cache(cache_path, cache)

    rows.sort(key=lambda r: r.saved_at, reverse=True)
    dd = DashboardData(sessions=rows)
    day_map: dict[str, DayRow] = {}
    day_costs: dict[str, list[float]] = {}
    day_tokens: dict[str, list[float]] = {}

    for r in rows:
        dd.total_sessions += 1
        dd.total_turns += r.turn_count
        dd.total_user_loops += r.user_loop_count
        dd.total_tool_loops += r.tool_loop_count
        dd.total_tool_calls += r.tool_call_count
        dd.total_input_tokens += r.input_tokens
        dd.total_output_tokens += r.output_tokens
        dd.total_cache_read_tokens += r.cache_read_tokens
        dd.total_cache_write_tokens += r.cache_write_tokens
        dd.total_cost += r.cost

        dr = day_map.get(r.date)
        if dr is None:
            dr = DayRow(date=r.date)
            day_map[r.date] = dr
            day_costs[r.date] = []
            day_tokens[r.date] = []
        dr.sessions += 1
        dr.turns += r.turn_count
        dr.user_loops += r.user_loop_count
        dr.tool_loops += r.tool_loop_count
        dr.tool_calls += r.tool_call_count
        dr.input_tokens += r.input_tokens
        dr.output_tokens += r.output_tokens
        dr.cache_read_tokens += r.cache_read_tokens
        dr.cache_write_tokens += r.cache_write_tokens
        dr.cost += r.cost
        day_costs[r.date].append(r.cost)
        day_tokens[r.date].append(float(r.input_tokens + r.output_tokens))

    for date, dr in day_map.items():
        costs = day_costs[date]
        tokens = day_tokens[date]
        dr.avg_cost = dr.cost / dr.sessions if dr.sessions else 0.0
        dr.median_cost = _safe_median(costs)
        dr.avg_tokens = sum(tokens) / len(tokens) if tokens else 0.0
        dr.median_tokens = _safe_median(tokens)

    dd.days = sorted(day_map.values(), key=lambda d: d.date, reverse=True)
    return dd
