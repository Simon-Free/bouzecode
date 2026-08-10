# [desc] Persiste/charge/supprime `<session>.deferred.json` ({answer, checks}) pour drainer les checks différés. [/desc]
"""Persist/load/delete `.deferred.json` next to a web-agent session file.

Written when `DeferredChecks` is raised at FinalAnswer; read by the web runner
to drain the queued commands after the model is unloaded. On a failing check the
agent is respawned via `--resume-deferred`. Lives as `<session_path>.deferred.json`
and holds `{"answer": str, "checks": list[dict]}`.
"""
from __future__ import annotations

import json
from pathlib import Path


def deferred_path(session_path: str | Path) -> Path:
    return Path(str(session_path) + ".deferred.json")


def save(session_path: str | Path, exc) -> None:
    """Serialize a DeferredChecks to disk next to the session."""
    payload = {
        "answer": exc.answer,
        "checks": exc.checks,
    }
    deferred_path(session_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def load(session_path: str | Path) -> dict | None:
    path = deferred_path(session_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete(session_path: str | Path) -> None:
    path = deferred_path(session_path)
    if path.exists():
        path.unlink()


def exists(session_path: str | Path) -> bool:
    return deferred_path(session_path).exists()
