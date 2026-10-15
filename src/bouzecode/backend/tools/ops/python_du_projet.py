# [desc] RunPythonTest : l'interpréteur d'un venv EXISTANT qui exécutera pytest directement (venv du projet, du dépôt principal, du process) ; jamais `uv run` quand un venv existe [/desc]
"""Le 2026-10-14, `uv run --directory demoapp_clone pytest` (sans `--no-sync`) a SYNCHRONISÉ le
venv partagé de demoapp_clone : réinstallation de `demoapp` (et de `Scripts/demoapp.exe`),
`cryptography` à moitié désinstallé parce qu'un autre agent tenait `_rust.pyd`. Règle depuis :
dès qu'un venv existe, son python est EXÉCUTÉ (`<python> -m pytest`) ; il n'est jamais
synchronisé, complété ni modifié. `uv run --no-sync` ne sert que s'il n'existe aucun venv.

Un `.venv` sans pytest (coquille laissée par `uv run`) ne vaut pas un venv qui en a un : un
venv porteur de pytest passe d'abord ; à défaut, le venv du projet est quand même pris, et
l'absence de pytest est DITE, jamais réparée."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ...testd.common import sans_fenetre

_BIN = "Scripts" if sys.platform == "win32" else "bin"
_PYTHON = "python.exe" if sys.platform == "win32" else "python"


def venv_a_pytest(venv: Path) -> bool:
    """Ce venv porte-t-il un pytest exécutable (seul critère qui distingue un venv prêt d'une
    coquille vide) ?"""
    return any((Path(venv) / _BIN / nom).exists() for nom in ("pytest.exe", "pytest"))


def venv_du_depot_principal(project_root: Path) -> str:
    """`<dépôt principal>/<même sous-dossier>/.venv` quand `project_root` est dans un worktree
    git lié (le worktree, sorti de git, n'a pas de `.venv`) ; "" sinon."""
    from ..environment import _main_repo_and_base
    sortie = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=project_root,
                            capture_output=True, text=True, timeout=30, **sans_fenetre())
    racine_worktree = os.path.normpath(sortie.stdout.strip()) if sortie.returncode == 0 else ""
    depot_principal = _main_repo_and_base(str(project_root))[0]
    if not (racine_worktree and depot_principal) or Path(racine_worktree) == Path(depot_principal):
        return ""
    relatif = os.path.relpath(project_root, racine_worktree)
    return str(Path(depot_principal) / relatif / ".venv")


def python_du_projet(project_root: Path, env: dict[str, str]) -> str | None:
    """Python à exécuter directement ; None seulement s'il n'existe AUCUN venv utilisable.

    Ordre : venv du projet, venv du projet dans le dépôt principal (worktree), puis
    `VIRTUAL_ENV` et le venv de ce process — ces deux derniers seulement s'ils portent pytest
    (dans un worktree de demo_application, ce sont ceux de bouzecode, sans les dépendances)."""
    du_projet = [Path(project_root) / ".venv"]
    principal = venv_du_depot_principal(Path(project_root))
    if principal:
        du_projet.append(Path(principal))
    du_process = [Path(c) for c in (env.get("VIRTUAL_ENV", ""), sys.prefix) if c]
    for venv in du_projet + du_process:
        if venv_a_pytest(venv) and (venv / _BIN / _PYTHON).exists():
            return str(venv / _BIN / _PYTHON)
    for venv in du_projet:
        if (venv / _BIN / _PYTHON).exists():
            return str(venv / _BIN / _PYTHON)
    return None


def module_absent(python: str, module: str, env: dict) -> bool:
    """Le module n'est pas importable par ce python (sonde en lecture seule)."""
    sonde = subprocess.run([python, "-c", f"import {module}"], capture_output=True, env=env,
                           timeout=60, **sans_fenetre())
    return sonde.returncode != 0
