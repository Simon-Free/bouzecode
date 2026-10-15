# [desc] Message « chemin inexistant » pour Grep/Glob/Read, avec les chemins réels proches (même nom plus bas, voisins au nom voisin). [/desc]
"""Dire qu'un chemin n'existe pas, et où est probablement celui qu'on voulait.

Constat sur 70 sessions réelles : l'agent cherchait `PycharmProjects\\bouzecode` alors que le
dépôt vit dans `PycharmProjects\\demo\\bouzecode`. Grep/Glob répondaient « aucun résultat »
sur ce chemin inexistant, et l'agent reformulait son MOTIF pendant 2 à 5 tours au lieu de
corriger son CHEMIN. On nomme donc le problème, puis on propose deux familles de candidats,
à partir du dernier dossier qui existe :
  - un dossier portant le nom manquant, un peu plus bas (le cas demo\\bouzecode), en
    privilégiant ceux où la suite du chemin existe aussi ;
  - les voisins au nom proche (faute de frappe, suffixe `-claude`, `_wt`...).
La recherche est BORNÉE (profondeur et nombre de dossiers) : ce message ne doit jamais coûter
plus cher que l'erreur qu'il évite.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages", ".tox",
}
_MAX_DEPTH = 3
_MAX_DIRS = 3000
_MAX_CANDIDATES = 5


def _split_existing(path: Path) -> tuple[Path | None, list[str]]:
    """(dernier ancêtre existant, composants manquants à partir de lui)."""
    missing: list[str] = []
    current = path
    while not current.exists():
        if current.parent == current:
            return None, [path.name]
        missing.insert(0, current.name)
        current = current.parent
    return current, missing


def _same_name_below(base: Path, name: str) -> list[Path]:
    """Dossiers nommés `name` (casse ignorée) sous `base`, en largeur d'abord, bornés."""
    target = name.lower()
    found: list[Path] = []
    frontier = [base]
    visited = 0
    for _depth in range(_MAX_DEPTH):
        nxt: list[Path] = []
        for folder in frontier:
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False) or entry.name in _SKIP_DIRS:
                    continue
                visited += 1
                child = Path(entry.path)
                if entry.name.lower() == target and folder != base:
                    found.append(child)
                nxt.append(child)
                if visited >= _MAX_DIRS:
                    return found
        frontier = nxt
    return found


def suggest_paths(path: str) -> tuple[Path | None, list[str]]:
    """(dernier dossier existant, chemins réels proposés à la place de `path`)."""
    wanted = Path(path)
    base, missing = _split_existing(wanted)
    if base is None or not missing or not base.is_dir():
        return base, []
    head, rest = missing[0], missing[1:]
    scored: list[tuple[int, str]] = []
    for folder in _same_name_below(base, head):
        full = folder.joinpath(*rest) if rest else folder
        scored.append((0 if full.exists() else 1, str(full if full.exists() else folder)))
    try:
        siblings = [e.name for e in os.scandir(base) if e.is_dir()]
    except OSError:
        siblings = []
    for name in difflib.get_close_matches(head, siblings, n=3, cutoff=0.6):
        full = base.joinpath(name, *rest)
        scored.append((0 if full.exists() else 2, str(full if full.exists() else base / name)))
    seen: set[str] = set()
    out: list[str] = []
    for _rank, cand in sorted(scored):
        if cand not in seen:
            seen.add(cand)
            out.append(cand)
    return base, out[:_MAX_CANDIDATES]


def missing_path_message(path: str) -> str:
    """Le message d'erreur complet pour un chemin de recherche/lecture inexistant."""
    base, candidates = suggest_paths(path)
    msg = f"Error: chemin inexistant : {path}"
    if base is not None:
        msg += f"\nDernier dossier existant : {base}"
    if candidates:
        msg += "\nChemins réels proches — relance sur l'un d'eux :\n" + "\n".join(
            f"  {c}" for c in candidates)
    return msg
