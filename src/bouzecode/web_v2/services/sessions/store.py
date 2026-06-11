# [desc] Index, résolution par clé et statut des sessions (agents web + sessions CLI daily). [/desc]
"""Source de vérité = les JSON de session écrits par save_progressive(), jamais le stdout.

Clés de session :
  - ``agent/<agent_id>``                      → agent web (~/.bouzecode/web_agents/)
  - ``daily/<YYYY-MM-DD>/<session_x.json>``   → session CLI (~/.bouzecode/sessions/daily/)
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ....web import runner

DAILY_DIR = Path.home() / ".bouzecode" / "sessions" / "daily"
CACHE_PATH = Path.home() / ".bouzecode" / "web_v2" / "index_cache.json"
_KEY_AGENT = re.compile(r"^agent/([0-9a-f]{6,32})$")
_KEY_DAILY = re.compile(r"^daily/(\d{4}-\d{2}-\d{2})/(session_[A-Za-z0-9_.]+\.json)$")
MAX_DAYS_LISTED = 10


@dataclass
class SessionRef:
    key: str
    kind: str  # "agent" | "daily"
    path: Path
    agent: runner.Agent | None = None


def resolve(key: str) -> SessionRef | None:
    """Résout une clé en chemin validé (aucun chemin arbitraire accepté)."""
    agent_match = _KEY_AGENT.match(key)
    if agent_match:
        agent = runner.load_agent(agent_match.group(1))
        if agent is None:
            return None
        return SessionRef(key=key, kind="agent", path=Path(agent.session_path), agent=agent)
    daily_match = _KEY_DAILY.match(key)
    if daily_match and ".." not in key:
        path = DAILY_DIR / daily_match.group(1) / daily_match.group(2)
        if path.is_file():
            return SessionRef(key=key, kind="daily", path=path)
    return None


def load_session_json(path: Path) -> dict | None:
    """Lecture tolérante : une sauvegarde progressive peut être en cours d'écriture."""
    for attempt in range(2):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt == 0:
                time.sleep(0.05)
    return None


def agent_status(agent: runner.Agent) -> dict:
    """Statut consolidé process + IPC. L'agent peut être mort ET en attente de réponse
    (AskUserQuestion persiste l'état IPC puis quitte le process)."""
    agent = runner.refresh_agent_status(agent)
    ipc_state = runner.get_ipc_state(agent)
    if ipc_state.get("status") == "awaiting_input":
        state = "awaiting_input"
    elif ipc_state.get("status") == "awaiting_plan_validation":
        state = "awaiting_plan_validation"
    elif runner.is_running(agent):
        state = "running"
    else:
        state = "finished"
    return {
        "state": state,
        "question": ipc_state.get("question", ""),
        "options": ipc_state.get("options") or [],
        "allow_freetext": ipc_state.get("allow_freetext", True),
        "returncode": agent.returncode,
    }


def _load_cache() -> dict:
    if CACHE_PATH.is_file():
        cached = load_session_json(CACHE_PATH)
        if isinstance(cached, dict):
            return cached
    return {}


def _save_cache(cache: dict) -> None:
    """Écriture best-effort : un tmp unique par appel (threads Flask et instances
    concurrentes), et une course perdue sur le replace Windows (WinError 32)
    abandonne juste cette sauvegarde — le cache sera réécrit au prochain listing."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CACHE_PATH.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    tmp_path.write_text(json.dumps(cache), encoding="utf-8")
    try:
        tmp_path.replace(CACHE_PATH)
    except OSError:
        tmp_path.unlink(missing_ok=True)


def _session_meta(path: Path, cache: dict) -> dict:
    """Méta d'une session, mise en cache par mtime (évite de relire des JSON de plusieurs Mo)."""
    if not path.is_file():
        return {"first_message": "(pas encore de session)", "model": "", "turn_count": 0, "saved_at": ""}
    mtime = path.stat().st_mtime
    entry = cache.get(str(path))
    if entry and entry.get("mtime") == mtime:
        return entry["meta"]
    data = load_session_json(path) or {}
    meta = {
        "first_message": data.get("first_message") or path.name,
        "model": data.get("model", ""),
        "turn_count": data.get("turn_count", 0),
        "saved_at": data.get("saved_at", ""),
        "close_reason": data.get("close_reason", ""),
    }
    cache[str(path)] = {"mtime": mtime, "meta": meta}
    return meta


def list_sessions() -> dict:
    """Agents web (avec statut live) + sessions CLI des derniers jours."""
    cache = _load_cache()
    agents = []
    for agent in runner.list_agents():
        meta = _session_meta(Path(agent.session_path), cache)
        agents.append({
            "key": f"agent/{agent.agent_id}",
            "title": (agent.prompt or "").strip().split("\n")[0][:90] or agent.agent_id,
            "model": agent.model or meta["model"],
            "cwd": agent.cwd or "",
            "started_at": agent.started_at,
            "saved_at": meta["saved_at"],
            "turn_count": meta["turn_count"],
            "status": agent_status(agent),
            "close_reason": meta.get("close_reason", ""),
        })
    agents.sort(key=lambda item: item.get("saved_at") or item["started_at"], reverse=True)

    days = []
    if DAILY_DIR.exists():
        day_dirs = sorted((d for d in DAILY_DIR.iterdir() if d.is_dir()), reverse=True)
        for day_dir in day_dirs[:MAX_DAYS_LISTED]:
            rows = []
            for session_file in day_dir.glob("session_*.json"):
                if session_file.name.endswith(".bak.json"):
                    continue
                meta = _session_meta(session_file, cache)
                rows.append({
                    "key": f"daily/{day_dir.name}/{session_file.name}",
                    "title": str(meta["first_message"])[:90],
                    "model": meta["model"],
                    "turn_count": meta["turn_count"],
                    "saved_at": meta["saved_at"],
                    "close_reason": meta.get("close_reason", ""),
                })
            rows.sort(key=lambda r: r["saved_at"] or "", reverse=True)
            if rows:
                days.append({"date": day_dir.name, "sessions": rows})
    _save_cache(cache)
    return {"agents": agents, "days": days}


def session_meta_full(data: dict) -> dict:
    """Méta affichée en tête de page session."""
    return {
        "first_message": data.get("first_message", ""),
        "model": data.get("model", ""),
        "turn_count": data.get("turn_count", 0),
        "saved_at": data.get("saved_at", ""),
        "input_tokens": data.get("total_input_tokens", 0),
        "output_tokens": data.get("total_output_tokens", 0),
        "files_edited": len(data.get("file_snapshots") or {}),
        "close_reason": data.get("close_reason", ""),
        "final_answer": data.get("final_answer", ""),
    }
