# [desc] Le venv de BASE d'un worktree d'agent = celui du MÊME projet (son checkout principal), jamais celui qui fait tourner bouzecode. [/desc]
"""Quel venv un worktree d'agent a-t-il le droit d'emprunter ?

LE DÉGÂT (2026-10-12, 11:48 et 14:40). Un sous-agent TUI travaille dans un worktree de
demo_application (Python 3.13). Faute de VIRTUAL_ENV, `worktree_child_env` lui donnait
« le venv de base » = `sys.prefix`, c'est-à-dire le venv de BOUZECODE (bouzecode\\.venv, 3.12),
avec UV_PROJECT_ENVIRONMENT pointé dessus. L'agent lance `uv sync --extra dev` : uv juge ce
venv 3.12 invalide pour un projet 3.13, vide `Lib\\`, puis échoue sur `Scripts\\` verrouillé
(os error 32). Le venv partagé de bouzecode est détruit deux fois dans la journée. UV_NO_SYNC=1 n'y
peut rien : il n'arrête pas un `uv sync` explicite.

LA RÈGLE. Le venv de base d'un worktree est celui de SON checkout principal, à la même
position relative (projet en sous-dossier du dépôt compris). Pas de venv du même projet →
aucun venv désigné, plutôt que celui d'un autre projet. Le checkout principal se lit sur le
DISQUE (`<wt>/.git` → gitdir → commondir), sans sous-process : ce calcul est fait à chaque
appel Bash.

DEPUIS LE 2026-10-12 (soir), la règle est GÉNÉRALE et vit dans `venv_du_projet` : hors worktree
aussi, le venv est celui du projet où l'agent travaille. Ce module garde les briques communes
(checkout principal d'un worktree, venv de bouzecode).
"""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path


def _norm(chemin: str) -> str:
    return os.path.normcase(os.path.abspath(chemin))


def _sous(chemin: str, racine: str) -> bool:
    """`chemin` est-il `racine` ou en dessous ? (comparaison sans casse sous Windows)"""
    c, r = _norm(chemin), _norm(racine)
    return c == r or c.startswith(r.rstrip(os.sep) + os.sep)


def venv_de_bouzecode() -> str:
    """Le venv qui fait tourner CE process bouzecode, "" hors venv."""
    return sys.prefix if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else ""


@functools.lru_cache(maxsize=128)
def depot_principal(worktree: str) -> str:
    """Racine du checkout PRINCIPAL dont `worktree` est un worktree git, "" si indéterminable.

    Un checkout principal a un DOSSIER `.git` : c'est lui-même. Un worktree a un FICHIER
    `.git` (`gitdir: <commun>/worktrees/<nom>`), dont le `commondir` désigne le `.git`
    partagé ; son parent est le checkout principal. Lu une fois par worktree (cache)."""
    dot_git = Path(worktree) / ".git"
    if dot_git.is_dir():
        return str(Path(worktree))
    if not dot_git.is_file():
        return ""
    contenu = dot_git.read_text(encoding="utf-8", errors="replace").strip()
    if not contenu.startswith("gitdir:"):
        return ""
    gitdir = Path(contenu[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = Path(worktree) / gitdir
    commun = gitdir
    fichier_commondir = gitdir / "commondir"
    if fichier_commondir.is_file():
        relatif = Path(fichier_commondir.read_text(encoding="utf-8", errors="replace").strip())
        commun = relatif if relatif.is_absolute() else gitdir / relatif
    commun = Path(os.path.normpath(commun))
    return str(commun.parent) if commun.name.lower() == ".git" else ""
