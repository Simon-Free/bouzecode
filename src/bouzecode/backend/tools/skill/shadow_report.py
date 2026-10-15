# [desc] Announces each genuine skill shadowing once on stderr; a copy of the SAME repo file (main checkout vs one of its worktrees) is only logged at debug level. [/desc]
"""Shadowing must be loud — but only when it means something.

A worktree is a checkout of the same repository as the main checkout: its
``.bouzecode/skills/x/skill.md`` IS the main checkout's file, on another branch. Reporting
"x (main) masquée par x (worktree)" for every skill of the project buried the genuine
conflicts (two different files answering to one name) under dozens of identical lines.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG = logging.getLogger("bouzecode.skill.shadow")

_REPORTED_SHADOWS: set[tuple[str, str, str]] = set()


def repo_identity(path: Path) -> tuple[Path, str] | None:
    """(main repository root, path relative to its checkout) for a file inside a git
    checkout — identical for the main checkout and every linked worktree — else None.

    A linked worktree's ``.git`` is a FILE holding ``gitdir: <main>/.git/worktrees/<n>``;
    read directly, no `git` subprocess on a path walked at every skill load.
    """
    resolved = Path(path).resolve()
    for base in resolved.parents:
        marker = base / ".git"
        if marker.is_dir():
            return base, resolved.relative_to(base).as_posix()
        if not marker.is_file():
            continue
        pointer = marker.read_text(encoding="utf-8", errors="replace").strip()
        gitdir = Path(pointer.split(":", 1)[1].strip()) if pointer.startswith("gitdir:") else None
        if gitdir is None or gitdir.parent.name != "worktrees":
            return None
        return gitdir.parent.parent.parent.resolve(), resolved.relative_to(base).as_posix()
    return None


def same_repo_file(first: str, second: str) -> bool:
    """True when both paths are the same file of the same repository, in two checkouts."""
    identity = repo_identity(Path(first))
    return identity is not None and identity == repo_identity(Path(second))


def report_shadows(resolution) -> None:
    """One stderr line per newly observed GENUINE shadowing. Costs zero context tokens.

    Deduplicated for the life of the process: skills are reloaded several times per tool
    call, and a warning repeated 40 times is a warning nobody reads. Inside an in-process
    sub-agent, stderr is that agent's own log (core/sortie_agent.py), not the main terminal.
    """
    for name in sorted(resolution.shadowed):
        winner = resolution.by_name(name)
        for loser in resolution.shadowed[name]:
            key = (name, winner.file_path, loser.file_path)
            if key in _REPORTED_SHADOWS:
                continue
            _REPORTED_SHADOWS.add(key)
            line = f"[skill] '{name}' ({loser.file_path}) masquée par ({winner.file_path})"
            if same_repo_file(loser.file_path, winner.file_path):
                _LOG.debug("%s — même fichier du même dépôt (autre checkout)", line)
                continue
            print(line, file=sys.stderr)
