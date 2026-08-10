# [desc] Recrée les liens répertoire vers les vrais dépôts pour que uv sync résolve les [tool.uv.sources] relatives dans un worktree.
# 
# Recrée les liens répertoire vers les vrais dépôts pour que uv sync résolve les [tool.uv.sources] relatives dans un worktree. [/desc]
"""Un worktree vit sous ~/.bouzecode/worktrees/<repo>/<ticket>/. Les `[tool.uv.sources]`
à chemin relatif (ex. `../bouzecode`, `../shared/libdb`) y pointent alors vers un
sibling INEXISTANT → `uv sync` échoue et le venv n'est jamais provisionné (venv_ok=False).
On recrée ces siblings comme des liens répertoire vers les VRAIS dépôts (résolus depuis le
repo d'origine), de façon idempotente, pour que `uv sync` résolve les deps editables
exactement comme dans le repo principal.

Windows : une JONCTION périmée (créée par un run précédent, cible disparue) n'apparaît ni
comme `exists()` ni comme `is_symlink()` mais bloque toute recréation (WinError 183). On la
détecte via le reparse-tag de `lstat` et on la remplace si elle ne pointe pas déjà au bon
endroit."""
from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path


def link_editable_sources(worktree: Path, repo_root: str) -> None:
    """Pour chaque source `[tool.uv.sources]` à chemin relatif qui échappe du worktree
    (`..`), garantit à l'emplacement attendu par uv un lien vers le vrai dépôt sibling
    (même chemin relatif, mais résolu depuis repo_root). Idempotent."""
    pyproject = worktree / "pyproject.toml"
    if not pyproject.is_file():
        return
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    for src in sources.values():
        rel = src.get("path") if isinstance(src, dict) else None
        if not rel or Path(rel).is_absolute() or ".." not in Path(rel).parts:
            continue
        expected = Path(os.path.normpath(worktree / rel))
        real = Path(os.path.normpath(Path(repo_root) / rel))
        if real.is_dir():
            _ensure_dir_link(expected, real)


def _ensure_dir_link(link: Path, target: Path) -> None:
    """Garantit link → target (symlink répertoire ; repli jonction Windows `mklink /J`).
    Un lien déjà correct est laissé tel quel ; un point de reparse périmé/erroné est retiré
    puis recréé. On ne touche JAMAIS un vrai dossier peuplé."""
    if _links_to(link, target):
        return
    if os.path.lexists(link):
        _remove_reparse_point(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, timeout=30)


def _links_to(link: Path, target: Path) -> bool:
    """True si link existe déjà et résout (jonction/symlink comprise) vers target."""
    if not os.path.lexists(link):
        return False
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


def _remove_reparse_point(link: Path) -> None:
    """Retire un lien/jonction (le point de reparse, jamais sa cible). No-op — et surtout
    aucune destruction — sur un vrai dossier peuplé."""
    tag = getattr(os.lstat(link), "st_reparse_tag", 0)
    if not tag and not os.path.islink(link):
        return  # vrai dossier : on n'y touche pas
    try:
        os.rmdir(link)      # jonction / symlink-dir : retire le reparse point
    except OSError:
        os.unlink(link)     # symlink-fichier / lien cassé
