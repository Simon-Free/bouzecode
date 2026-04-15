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


def cancel(session_path: str | Path) -> bool:
    """Inject synthetic `(cancelled by user)` tool_results for unresolved pending tcs
    into the session so the conversation stays API-valid, then delete pending.json.
    Returns True if pending was present and cancelled, False otherwise."""
    data = load(session_path)
    if data is None:
        return False
    sp = Path(session_path)
    if not sp.exists():
        delete(session_path)
        return True

    session = json.loads(sp.read_text(encoding="utf-8"))
    messages = session.get("messages", [])
    already_resolved = {
        m.get("tool_call_id") for m in messages if m.get("role") == "tool"
    }

    unresolved_tcs = [
        tc for tc in data.get("pending_tcs", [])
        if tc["id"] not in already_resolved
    ]
    if data.get("ask_tc_id") and data["ask_tc_id"] not in already_resolved:
        if not any(tc["id"] == data["ask_tc_id"] for tc in unresolved_tcs):
            unresolved_tcs.insert(0, {"id": data["ask_tc_id"], "name": "AskUserQuestion"})

    for tc in unresolved_tcs:
        messages.append({
            "role": "tool", "tool_call_id": tc["id"],
            "name": tc.get("name", "Unknown"), "content": "(cancelled by user)",
        })

    session["messages"] = messages
    sp.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    delete(session_path)
    return True
