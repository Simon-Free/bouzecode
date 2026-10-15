# [desc] RunPythonTest dans un worktree git sans `.venv` lance le python du `.venv` du projet dans le dépôt principal, pas celui du process (bouzecode). [/desc]
"""Session 9d81964e (2026-10-06) : dans un worktree de demo_application, RunPythonTest a
lancé pytest avec le venv de bouzecode (ImportError au conftest), puis 2 tours pour trouver
le bon interpréteur. Vrai dépôt git, vrai worktree."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bouzecode.backend.tools.ops.test_runner import _python_without_uv, venv_du_depot_principal


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _depot_avec_worktree(tmp_path: Path) -> tuple[Path, Path]:
    principal, worktree = tmp_path / "principal", tmp_path / "wt"
    (principal / "projet").mkdir(parents=True)
    (principal / "projet" / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    _git("init", "-q", cwd=principal)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "projet/pyproject.toml",
         cwd=principal)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init",
         cwd=principal)
    _git("worktree", "add", "-q", str(worktree), "-b", "agent/solo", cwd=principal)
    binaires = principal / "projet" / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    binaires.mkdir(parents=True)
    for nom in ("python.exe", "pytest.exe", "python", "pytest"):
        (binaires / nom).write_text("", encoding="utf-8")
    return principal, worktree


def test_worktree_sans_venv_prend_le_venv_du_projet_dans_le_depot_principal(tmp_path):
    principal, worktree = _depot_avec_worktree(tmp_path)
    attendu = principal / "projet" / ".venv"
    assert Path(venv_du_depot_principal(worktree / "projet")) == attendu
    python = _python_without_uv(worktree / "projet", {"VIRTUAL_ENV": sys.prefix})
    assert Path(python).parent.parent == attendu


def test_dans_le_depot_principal_rien_ne_change(tmp_path):
    principal, _ = _depot_avec_worktree(tmp_path)
    assert venv_du_depot_principal(principal / "projet") == ""
