# [desc] Persistence of paused turn state (AskUserQuestion awaiting answer) next to session files. [/desc]
"""Persist/load/delete `.pending.json` next to a web-agent session file.

Written when `PausedForInput` is raised; read by `--resume-pending` to inject
the user's answer and finish executing the remaining tool_calls of the paused
turn. Lives as `<session_path>.pending.json`.
"""
from __future__ import annotations

import json
from pathlib import Path


def pending_path(session_path: str | Path) -> Path:
    return Path(str(session_path) + ".pending.json")


def save(session_path: str | Path, pause) -> None:
    """Serialize a PausedForInput to disk next to the session."""
    payload = {
        "ask_tc_id": pause.ask_tc_id,
        "question": pause.question,
        "options": pause.options,
        "allow_freetext": pause.allow_freetext,
        "completed_results": pause.completed_results,
        "pending_tcs": pause.pending_tcs,
    }
    pending_path(session_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def load(session_path: str | Path) -> dict | None:
    path = pending_path(session_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete(session_path: str | Path) -> None:
    path = pending_path(session_path)
    if path.exists():
        path.unlink()


def exists(session_path: str | Path) -> bool:
    return pending_path(session_path).exists()


def _unresolved(data: dict, already_resolved: set) -> list[dict]:
    """Appels d'outils en pause encore sans résultat, la question (ask_tc_id) en tête."""
    unresolved = [tc for tc in data.get("pending_tcs", []) if tc["id"] not in already_resolved]
    ask_id = data.get("ask_tc_id")
    if ask_id and ask_id not in already_resolved and not any(tc["id"] == ask_id for tc in unresolved):
        unresolved.insert(0, {"id": ask_id, "name": "AskUserQuestion"})
    return unresolved


def _inject_cancelled(session_file: Path, data: dict) -> None:
    session = json.loads(session_file.read_text(encoding="utf-8"))
    messages = session.get("messages", [])
    resolved = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    for tc in _unresolved(data, resolved):
        messages.append({"role": "tool", "tool_call_id": tc["id"],
                         "name": tc.get("name", "Unknown"), "content": "(cancelled by user)"})
    session["messages"] = messages
    session_file.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")


def cancel(session_path: str | Path) -> bool:
    """Inject synthetic `(cancelled by user)` tool_results for unresolved pending tcs
    into the session so the conversation stays API-valid, then delete pending.json.
    Returns True if pending was present and cancelled, False otherwise."""
    data = load(session_path)
    if data is None:
        return False
    if Path(session_path).exists():
        _inject_cancelled(Path(session_path), data)
    delete(session_path)
    return True
