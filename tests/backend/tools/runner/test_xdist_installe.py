# [desc] RunPythonTest avec -n dans un projet dont le venv n'a pas pytest-xdist : l'absence est dite, rien n'est installé dans ce venv. [/desc]
"""Un lancement parallèle (`-n`) ne doit plus mourir sur « unrecognized arguments: -n ».

Constaté au T37 de la session DeepSeek du rapport `docs/reduction_tokens/rapport.md` : un
tour entier perdu parce que le venv du projet n'avait pas pytest-xdist. Depuis le 2026-10-14
un venv existant n'est jamais modifié : l'absence est dite AVANT le lancement, avec le remède
(`parallel='off'`).

Hermétique : le venv du projet est créé par uv à partir de son cache (`UV_OFFLINE=1`) ; le
test est sauté si ce cache ne fournit pas pytest et pytest-xdist.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from bouzecode.backend.tools.ops.test_runner import run_python_test

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or sys.platform == "win32", reason="uv requis (Linux)")


def _projet_sans_xdist(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    (tmp_path / "test_demo.py").write_text("def test_un():\n    assert 1\n\ndef test_deux():\n    assert 2\n")
    py = tmp_path / ".venv" / "bin" / "python"
    for cmd in (["uv", "venv", "-q", str(tmp_path / ".venv")],
                ["uv", "pip", "install", "-q", "--offline", "--python", str(py), "pytest"]):
        if subprocess.run(cmd, capture_output=True).returncode != 0:
            pytest.skip("le cache uv ne fournit pas pytest hors ligne")
    return py


def test_xdist_absent_est_dit_et_rien_n_est_installe(tmp_path, monkeypatch):
    py = _projet_sans_xdist(tmp_path)
    monkeypatch.setenv("UV_OFFLINE", "1")
    assert subprocess.run([str(py), "-c", "import xdist"], capture_output=True).returncode != 0

    result = run_python_test(targets=[str(tmp_path / "test_demo.py")], parallel="2",
                             timeout=120, no_sync=True)

    assert result.startswith("Error:") and "pytest-xdist absent" in result
    assert "parallel='off'" in result
    assert subprocess.run([str(py), "-c", "import xdist"], capture_output=True).returncode != 0


def test_xdist_present_rien_n_est_installe(tmp_path, monkeypatch):
    py = _projet_sans_xdist(tmp_path)
    monkeypatch.setenv("UV_OFFLINE", "1")
    if subprocess.run(["uv", "pip", "install", "-q", "--offline", "--python", str(py),
                       "pytest-xdist"], capture_output=True).returncode != 0:
        pytest.skip("le cache uv ne fournit pas pytest-xdist hors ligne")

    result = run_python_test(targets=[str(tmp_path / "test_demo.py")], parallel="2",
                             timeout=120, no_sync=True)

    assert "pytest-xdist absent" not in result
    assert "2 passed" in result
