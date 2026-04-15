# [desc] Scans saved session files to compute aggregate token usage and cost statistics for a dashboard. [/desc]
"""Scan saved sessions and compute aggregate token / cost statistics."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from providers.registry import calc_cost

_DEFAULT_MODEL = "claude-opus-4-6"


@dataclass
class SessionRow:
    session_id: str
    saved_at: str
    date: str
    first_message: str
    turn_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost: float
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class DayRow:
    date: str
    sessions: int = 0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class DashboardData:
    total_sessions: int = 0
    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cost: float = 0.0
    sessions: list[SessionRow] = field(default_factory=list)
    days: list[DayRow] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return (self.total_input_tokens + self.total_output_tokens
                + self.total_cache_read_tokens + self.total_cache_creation_tokens)


def _parse_session(data: dict) -> SessionRow | None:
    sid = data.get("session_id", "")
    if not sid:
        return None
    saved = data.get("saved_at", "")
    date = saved[:10] if len(saved) >= 10 else ""
    in_tok = data.get("total_input_tokens", 0) or 0
    out_tok = data.get("total_output_tokens", 0) or 0
    cache_r = data.get("total_cache_read_tokens", 0) or 0
    cache_c = data.get("total_cache_creation_tokens", 0) or 0
    model = data.get("model") or _DEFAULT_MODEL
    return SessionRow(
        session_id=sid,
        saved_at=saved,
        date=date,
        first_message=data.get("first_message", ""),
        turn_count=data.get("turn_count", 0) or 0,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cache_r,
        cache_creation_tokens=cache_c,
        cost=calc_cost(model, in_tok, out_tok, cache_r, cache_c),
        model=model,
    )


def get_dashboard_data() -> DashboardData:
    from config import DAILY_DIR

    seen_ids: set[str] = set()
    rows: list[SessionRow] = []

    if DAILY_DIR.exists():
        for day_dir in sorted(DAILY_DIR.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue
            for fp in sorted(day_dir.glob("session_*.json"), reverse=True):
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                row = _parse_session(data)
                if row and row.session_id not in seen_ids:
                    seen_ids.add(row.session_id)
                    rows.append(row)

    rows.sort(key=lambda r: r.saved_at, reverse=True)
    dd = DashboardData(sessions=rows)
    day_map: dict[str, DayRow] = {}

    for r in rows:
        dd.total_sessions += 1
        dd.total_turns += r.turn_count
        dd.total_input_tokens += r.input_tokens
        dd.total_output_tokens += r.output_tokens
        dd.total_cache_read_tokens += r.cache_read_tokens
        dd.total_cache_creation_tokens += r.cache_creation_tokens
        dd.total_cost += r.cost

        dr = day_map.get(r.date)
        if dr is None:
            dr = DayRow(date=r.date)
            day_map[r.date] = dr
        dr.sessions += 1
        dr.turns += r.turn_count
        dr.input_tokens += r.input_tokens
        dr.output_tokens += r.output_tokens
        dr.cache_read_tokens += r.cache_read_tokens
        dr.cache_creation_tokens += r.cache_creation_tokens
        dr.cost += r.cost

    dd.days = sorted(day_map.values(), key=lambda d: d.date, reverse=True)
    return dd
