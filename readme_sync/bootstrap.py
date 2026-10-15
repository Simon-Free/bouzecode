# One-shot / recheck driver: (re)generate folder READMEs + root map at agent launch.
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from .hashing import code_files, iter_code_folders, scan
from .propagate import SUBFOLDERS_HEADING, create_root_map
from .regen import regen_folder

DEFAULT_CAP = 20
# Above this many code folders a project is too big to auto-document at launch
# (likely a monorepo / vendored tree) — skip rather than churn hundreds of READMEs.
MAX_FOLDERS = 200
_DISABLED_VALUES = {"0", "false", "off", "no"}
# Temps que le lancement d'un agent accepte de PERDRE a se documenter lui-meme.
# Ce hook fait des appels LLM en serie (jusqu'a `cap`), sur le chemin critique du
# demarrage : sans plafond, un seul appel qui pend gele l'agent avant son premier
# tour. Genereux pour laisser passer un cas normal, fini pour que l'anomalie ne
# coute qu'une demi-minute.
DEADLINE_SECONDS = 30.0


def code_folder_count(root: Path) -> int:
    """Number of folders under root that directly contain code files."""
    return sum(1 for folder in iter_code_folders(root) if code_files(folder))


def _env_enabled() -> bool:
    """README sync at launch is ON by default (bounded by MAX_FOLDERS); opt out
    with BOUZECODE_README_SYNC=0 (or false/off/no)."""
    return os.environ.get("BOUZECODE_README_SYNC", "").strip().lower() not in _DISABLED_VALUES


def _is_linked_worktree(root: Path) -> bool:
    """A git worktree has a `.git` FILE (a gitdir pointer); the main checkout has
    a `.git` directory. Ticket worktrees are throwaway, so auto-documenting them
    would waste LLM calls on READMEs that get discarded and could pollute the
    ticket diff — never bootstrap inside one."""
    return (root / ".git").is_file()


def _root_map_present(root: Path) -> bool:
    """True when the root AGENTS.md exists AND already carries a Subfolders map."""
    doc = root / "AGENTS.md"
    if not doc.exists():
        return False
    return SUBFOLDERS_HEADING in doc.read_text(encoding="utf-8")


def bootstrap_readme_map(
    root: Path, cap: int = DEFAULT_CAP, client=None, max_folders: int = MAX_FOLDERS
) -> dict:
    """(Re)generate READMEs, capped and non-blocking-friendly.

    Skipped entirely when the project has `max_folders` or more code folders —
    too big to auto-document at launch. Otherwise: first launch (no root map)
    regenerates every flagged folder then builds the root map; recheck (root map
    present) regenerates ONLY the folders whose code changed. In both cases at
    most `cap` folders are regenerated this run; the rest are reported as
    `deferred` so a launch is never frozen.
    """
    root = root.resolve()
    if _is_linked_worktree(root):
        return {"disabled": False, "skipped": "worktree"}
    total_folders = code_folder_count(root)
    if total_folders >= max_folders:
        return {
            "disabled": False,
            "skipped": "too_many_folders",
            "folders": total_folders,
            "max": max_folders,
        }
    first_launch = not _root_map_present(root)

    flagged = [s for s in scan(root) if s.needs_attention]
    to_process = flagged[:cap]
    deferred = flagged[cap:]

    key = "generated" if first_launch else "regenerated"
    for status in to_process:
        regen_folder(status.path, root, client=client)

    if first_launch:
        create_root_map(root)

    return {
        "disabled": False,
        "first_launch": first_launch,
        key: [str(s.path) for s in to_process],
        "deferred": [str(s.path) for s in deferred],
    }


def maybe_bootstrap_readme(root: Path, cap: int = DEFAULT_CAP,
                           deadline: float = DEADLINE_SECONDS) -> dict:
    """Launch-time entry point: gated by env, never raises, never stalls.

    The `try/except` honoured "never raises" but NOT "never stalls": a call that
    hangs is not an exception. And this runs on the critical path of every agent
    launch — `web_v2/runtime/ipc.py` calls it between the run's `running` state
    and its first turn — so anything that blocks here freezes the agent BEFORE it
    has emitted a single line.

    Measured 2026-08-24: agents dispatched with `isolation='shared'` sat in
    `starting` forever, log frozen on one line, no LLM payload ever written. The
    py-spy stack showed the truth — `regen_folder` → `anthropic.messages.create`
    → blocked in `ssl.read`, no timeout anywhere. Worktree agents were unaffected
    for one reason only: `_is_linked_worktree` skips them (see `bootstrap_readme_map`),
    which is why the bug read as "shared isolation is broken".

    So the work runs in a daemon thread and we wait at most `deadline`. Past that
    the launch continues and the thread is abandoned — it is daemonic, so it can
    never hold the process open. Documenting folders is a convenience; starting
    the agent is the job.
    """
    if not _env_enabled():
        return {"disabled": True}

    outcome: dict = {}

    def _run() -> None:
        try:
            outcome.update(bootstrap_readme_map(root, cap=cap))
        except Exception as exc:  # non-blocking: log and continue the agent launch
            print(f"[readme_sync] bootstrap skipped: {exc}", file=sys.stderr)
            outcome.update({"disabled": False, "error": str(exc)})

    worker = threading.Thread(target=_run, name="readme-sync-bootstrap", daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        print(f"[readme_sync] bootstrap abandoned after {deadline:.0f}s — agent launch continues",
              file=sys.stderr)
        return {"disabled": False, "timeout": deadline}
    return outcome
