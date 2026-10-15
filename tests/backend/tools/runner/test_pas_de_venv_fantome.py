"""RunPythonTest ne laisse jamais derrière lui un `.venv` vide.

Constat sur les sessions réelles (poste Windows, worktrees d'agents) :
    $ uv run --no-sync --directory <worktree> pytest ...
    Creating virtual environment at: .venv
    error: Failed to spawn: `pytest` — Caused by: program not found
Le `.venv` vide reste, devient le venv le plus proche et masque le venv de base pour toute la
suite de la session. Si `uv run` en fabrique un malgré tout, on le retire et on le dit.
"""
import os
import sys

import pytest

from bouzecode.backend.tools.ops import test_runner


@pytest.mark.skipif(sys.platform == "win32", reason="faux uv en script shell")
def test_un_venv_cree_vide_par_uv_run_est_retire(tmp_path, monkeypatch):
    projet = tmp_path / "wt"
    (projet / "tests").mkdir(parents=True)
    (projet / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (projet / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    faux = tmp_path / "bin"
    faux.mkdir()
    uv = faux / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        "mkdir -p .venv/bin && echo 'home = /usr/bin' > .venv/pyvenv.cfg\n"
        "echo 'Creating virtual environment at: .venv'\n"
        "echo 'error: Failed to spawn: `pytest`'\n"
        "exit 2\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{faux}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(test_runner, "_python_without_uv", lambda *a, **k: None)
    out = test_runner.run_python_test(targets=[str(projet / "tests" / "test_a.py")],
                                      parallel="off", no_sync=True)
    assert not (projet / ".venv").exists()
    assert ".venv" in out and "retir" in out


@pytest.mark.skipif(sys.platform == "win32", reason="faux uv en script shell")
def test_un_venv_qui_existait_deja_nest_jamais_touche(tmp_path, monkeypatch):
    projet = tmp_path / "wt"
    (projet / ".venv" / "bin").mkdir(parents=True)
    (projet / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (projet / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    faux = tmp_path / "bin"
    faux.mkdir()
    (faux / "uv").write_text("#!/bin/sh\necho 'error: Failed to spawn'\nexit 2\n",
                             encoding="utf-8")
    (faux / "uv").chmod(0o755)
    monkeypatch.setenv("PATH", f"{faux}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(test_runner, "_python_without_uv", lambda *a, **k: None)
    test_runner.run_python_test(targets=[str(projet)], parallel="off", no_sync=True)
    assert (projet / ".venv" / "pyvenv.cfg").exists()
