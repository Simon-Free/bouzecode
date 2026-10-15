# [desc] Où se situe un chemin vis-à-vis du registre : projet désigné, écarté, inconnu, ou silencieux. [/desc]
"""Situer un dossier — sans jamais deviner.

Un dossier est un projet **parce que l'utilisateur l'a désigné**, jamais parce
qu'un marqueur le suggère. Ce module ne fait que consulter les deux listes et
répondre : désigné / écarté / inconnu.

Une seule exception : les worktrees. Il y en a des centaines, ils portent déjà
leur propre configuration, et ce ne sont pas des choses qu'on enregistre. C'est
un *silence* — on ne demande rien et on n'écrit rien — pas un refus.

Le dossier temporaire du système avait été envisagé comme second silence. Il a
été retiré : c'était encore une devinette, et si l'utilisateur veut désigner un
dossier jetable comme projet, ce n'est pas au code d'en juger.
"""
from __future__ import annotations

import os
from pathlib import Path

DESIGNATED = "designated"
DISMISSED = "dismissed"
UNKNOWN = "unknown"


def path_key(path: str | Path) -> str:
    """Forme comparable d'un chemin (absolu, résolu, casse normalisée)."""
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _worktrees_root() -> Path:
    from .....web_v2.services.work.worktrees import WORKTREES_DIR  # import local : Flask

    return Path(WORKTREES_DIR)


def is_silent(path: Path) -> str:
    """La raison de ne rien demander sur ce chemin, ou "" s'il faut le traiter normalement."""
    if path_key(path).startswith(path_key(_worktrees_root()) + os.sep):
        return "worktree"
    return ""


def all_projects() -> list[dict]:
    from .....web_v2.services.work.projects import list_projects

    return list_projects()


def find_project(path: Path) -> dict | None:
    """L'entrée du registre désignant exactement ce dossier, ou None."""
    key = path_key(path)
    return next((p for p in all_projects() if path_key(p["path"]) == key), None)


def registered_children(path: Path) -> list[dict]:
    """Les projets désignés dont le dossier est situé SOUS `path`.

    C'est ce qui permet de répondre utilement sur un conteneur comme `demo/` :
    on ne sait pas quoi en faire, mais on sait ce qu'il contient.
    """
    prefix = path_key(path) + os.sep
    return sorted(
        (p for p in all_projects() if path_key(p["path"]).startswith(prefix)),
        key=lambda p: p["name"],
    )


def other_projects(path: Path) -> list[dict]:
    """Les projets désignés hors de `path`, dont le dossier existe encore.

    Le filtre sur l'existence évite de proposer des entrées fantômes — le
    registre en accumule (un dossier temporaire supprimé y a longtemps traîné).
    """
    prefix = path_key(path) + os.sep
    return sorted(
        (p for p in all_projects()
         if not path_key(p["path"]).startswith(prefix)
         and path_key(p["path"]) != path_key(path)
         and Path(p["path"]).is_dir()),
        key=lambda p: p["name"],
    )


def status_of(path: Path) -> tuple[str, dict | None]:
    """(statut, entrée) — l'entrée est le projet désigné ou l'écart enregistré."""
    from .....web_v2.services.work.dismissed_paths import find_dismissal

    project = find_project(path)
    if project is not None:
        return DESIGNATED, project
    dismissal = find_dismissal(path)
    if dismissal is not None:
        return DISMISSED, dismissal
    return UNKNOWN, None
