"""Dans un worktree, les commandes de l'agent tournent avec le venv du dépôt de base et le
code DU WORKTREE — sans jamais fabriquer de `.venv` vide.

Constat sur 70 sessions réelles (poste Windows) : dans un worktree neuf, `uv sync` échoue
(401 sur l'index Artifactory, hatchling introuvable), `uv run` crée un `.venv` VIDE qui masque
le bon (« Failed to spawn: pytest — program not found »), et le contournement redécouvert à
chaque session était : python du venv principal + PYTHONPATH=<worktree>/src.
"""
import os
import sys

from bouzecode.backend.tools.ops import shell_env
from bouzecode.backend.tools.ops.shell_env import _get_env_with_user_vars, worktree_child_env
from bouzecode.backend.tools.ops.shell_search import _bash


def _venv(dossier):
    dossier.mkdir(parents=True)
    (dossier / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (dossier / ("Scripts" if os.name == "nt" else "bin")).mkdir()
    return dossier


def _worktree(tmp_path):
    wt = tmp_path / "worktrees" / "bouzecode" / "solo"
    (wt / "src" / "bouzecode").mkdir(parents=True)
    (wt / "pyproject.toml").write_text("[project]\nname='bouzecode'\n", encoding="utf-8")
    return wt


def test_le_code_du_worktree_passe_devant_celui_du_serveur(tmp_path):
    wt = _worktree(tmp_path)
    base = _venv(tmp_path / "demo" / "bouzecode" / ".venv")
    env = {"BOUZECODE_WORKTREE_ROOT": str(wt), "PYTHONPATH": "/serveur/src", "PATH": "/usr/bin"}
    out = worktree_child_env(env, base_venv=str(base))
    assert out["PYTHONPATH"].split(os.pathsep) == [str(wt / "src"), "/serveur/src"]
    assert out["UV_NO_SYNC"] == "1"
    assert out["VIRTUAL_ENV"] == str(base)
    assert out["PATH"].startswith(str(base))
    # sans lui, même `uv run --no-sync` crée `./.venv` dans le worktree
    assert out["UV_PROJECT_ENVIRONMENT"] == str(base)
    # idempotent : un second passage n'empile rien
    assert worktree_child_env(out, base_venv=str(base))["PYTHONPATH"] == out["PYTHONPATH"]


def test_un_venv_deja_designe_nest_pas_remplace(tmp_path):
    wt = _worktree(tmp_path)
    propre = _venv(wt / ".venv")
    env = {"BOUZECODE_WORKTREE_ROOT": str(wt), "VIRTUAL_ENV": str(propre), "PATH": "/usr/bin"}
    out = worktree_child_env(env, base_venv=str(tmp_path / "autre"))
    assert out["VIRTUAL_ENV"] == str(propre)
    assert "UV_NO_SYNC" not in out  # son propre venv : uv peut le synchroniser


def test_hors_worktree_rien_ne_change(tmp_path):
    env = {"PATH": "/usr/bin", "PYTHONPATH": "/x"}
    assert worktree_child_env(env, base_venv=str(tmp_path)) == env


def test_une_variable_posee_en_vol_atteint_le_bash_suivant(monkeypatch):
    """`Environment(action='venv'|'worktree')` mute os.environ pour « tes prochains Bash » :
    un instantané pris au premier Bash rendait cette promesse fausse."""
    monkeypatch.setattr(shell_env, "_user_registry_items", lambda: [], raising=False)
    monkeypatch.setenv("BZ_EN_VOL", "avant")
    assert _get_env_with_user_vars()["BZ_EN_VOL"] == "avant"
    monkeypatch.setenv("BZ_EN_VOL", "apres")
    assert _get_env_with_user_vars()["BZ_EN_VOL"] == "apres"


def test_bash_dans_un_worktree_voit_le_src_du_worktree(tmp_path, monkeypatch):
    if sys.platform == "win32":
        return
    wt = _worktree(tmp_path)
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(wt))
    out = _bash('echo "PP=$PYTHONPATH NS=$UV_NO_SYNC"')
    assert f"PP={wt / 'src'}" in out
    assert "NS=1" in out
