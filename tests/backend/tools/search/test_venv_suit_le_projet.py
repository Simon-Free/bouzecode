"""Les commandes d'un agent prennent le venv du PROJET où il travaille, quel que soit le chemin
qui l'y a mené.

Question de l'utilisateur, 2026-10-12 : « s'il travaille dans demo_application,
LoadProjectConfig devrait renvoyer le venv de demo_application non ? » — jusque-là, seul un
worktree d'agent recevait le venv de son projet ; hors worktree, `python` / `pytest` restaient
sur le venv hérité (celui de bouzecode).
"""
import os
import subprocess
import sys

import pytest

from bouzecode.backend.core import dossier_agent, paths
from bouzecode.backend.tools.ops import shell_env
from bouzecode.backend.tools.ops.project_config import _load_project_config
from bouzecode.backend.tools.ops.shell_env import worktree_child_env
from bouzecode.web_v2.services.work import dismissed_paths, projects

BIN = "Scripts" if os.name == "nt" else "bin"


def _venv(dossier):
    (dossier / BIN).mkdir(parents=True)
    (dossier / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return dossier


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


def _projet(racine):
    """Un dépôt git avec un pyproject.toml et son `.venv`."""
    racine.mkdir(parents=True)
    (racine / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", cwd=racine)
    _git("add", "pyproject.toml", cwd=racine)
    _git("commit", "-q", "-m", "init", cwd=racine)
    return racine, _venv(racine / ".venv")


def _designes(env):
    return {env.get("VIRTUAL_ENV", ""), env.get("UV_PROJECT_ENVIRONMENT", "")} - {""}


@pytest.fixture()
def bouzecode_dans_a(tmp_path, monkeypatch):
    """bouzecode tourne depuis le venv du projet A (bouzecode), qui est aussi le venv hérité."""
    projet_a, venv_a = _projet(tmp_path / "bouzecode")
    monkeypatch.setattr(sys, "prefix", str(venv_a))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "interpreteur"))
    return projet_a, venv_a


def _env_herite(venv_a):
    return {"VIRTUAL_ENV": str(venv_a), "UV_PROJECT_ENVIRONMENT": str(venv_a),
            "PATH": os.pathsep.join([str(venv_a / BIN), "/usr/bin"])}


def test_dans_le_checkout_principal_de_b_c_est_le_venv_de_b(tmp_path, bouzecode_dans_a):
    _, venv_a = bouzecode_dans_a
    projet_b, venv_b = _projet(tmp_path / "demo_application")

    out = worktree_child_env(_env_herite(venv_a), dossier=str(projet_b / "src"))

    assert _designes(out) == {str(venv_b)}
    chemins = out["PATH"].split(os.pathsep)
    assert chemins[0] == str(venv_b / BIN)
    assert str(venv_a / BIN) not in chemins
    assert "UV_NO_SYNC" not in out  # hors worktree : uv garde son comportement normal


def test_hors_de_tout_projet_aucun_venv_et_les_etrangers_sont_retires(tmp_path, bouzecode_dans_a):
    _, venv_a = bouzecode_dans_a
    nulle_part = tmp_path / "documents"
    nulle_part.mkdir()

    out = worktree_child_env(_env_herite(venv_a), dossier=str(nulle_part))

    assert _designes(out) == set()
    assert out["PATH"].split(os.pathsep) == ["/usr/bin"]


def test_dans_bouzecode_lui_meme_le_venv_de_bouzecode_reste_designe(bouzecode_dans_a):
    projet_a, venv_a = bouzecode_dans_a

    out = worktree_child_env(_env_herite(venv_a), dossier=str(projet_a))

    assert _designes(out) == {str(venv_a)}
    assert out["PATH"].split(os.pathsep) == [str(venv_a / BIN), "/usr/bin"]  # rien d'empilé


def test_un_agent_sorti_de_son_worktree_prend_le_venv_du_projet_ou_il_est(tmp_path, bouzecode_dans_a):
    projet_a, venv_a = bouzecode_dans_a
    wt = tmp_path / "worktrees" / "a-1"
    _git("worktree", "add", "-q", "-b", "a-1", str(wt), cwd=projet_a)
    projet_b, venv_b = _projet(tmp_path / "demo_application")
    env = dict(_env_herite(venv_a), BOUZECODE_WORKTREE_ROOT=str(wt), PYTHONPATH="/x")

    assert _designes(worktree_child_env(env, dossier=str(wt))) == {str(venv_a)}
    out = worktree_child_env(env, dossier=str(projet_b))
    assert _designes(out) == {str(venv_b)}
    assert out["PYTHONPATH"] == "/x"  # le src du worktree de A ne suit pas l'agent dans B


@pytest.fixture()
def registre_vide(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(dismissed_paths, "DISMISSED_PATH", tmp_path / "dismissed.json")
    monkeypatch.setattr(paths, "_extra_dirs", [], raising=False)
    monkeypatch.setattr(shell_env, "_user_registry_items", lambda: ())
    for nom in ("BOUZECODE_WORKTREE_ROOT", "BOUZECODE_WEB_IPC_DIR", "UV_PROJECT_ENVIRONMENT"):
        monkeypatch.delenv(nom, raising=False)


def test_apres_load_project_config_cd_le_bash_suivant_prend_le_venv_de_b(
        tmp_path, bouzecode_dans_a, registre_vide, monkeypatch):
    """Agent dans son propre process : le `cd` est un os.chdir, `courant()` le suit."""
    projet_a, venv_a = bouzecode_dans_a
    projet_b, venv_b = _projet(tmp_path / "demo_application")
    monkeypatch.chdir(projet_a)
    monkeypatch.setenv("VIRTUAL_ENV", str(venv_a))
    assert _designes(shell_env._get_env_with_user_vars()) == {str(venv_a)}

    _load_project_config(str(projet_b), {}, cd=True)

    assert os.path.samefile(dossier_agent.courant(), projet_b)
    assert _designes(shell_env._get_env_with_user_vars()) == {str(venv_b)}


def test_un_sous_agent_en_process_suit_aussi_son_load_project_config(
        tmp_path, bouzecode_dans_a, registre_vide, monkeypatch):
    """Sous-agent du TUI : son dossier est dans son Atelier, le process ne bouge pas."""
    projet_a, venv_a = bouzecode_dans_a
    projet_b, venv_b = _projet(tmp_path / "demo_application")
    monkeypatch.chdir(projet_a)
    atelier = dossier_agent.Atelier(dossier=str(projet_a), variables={"VIRTUAL_ENV": str(venv_a)})

    with dossier_agent.dans(atelier):
        _load_project_config(str(projet_b), {}, cd=True)
        assert os.path.samefile(dossier_agent.courant(), projet_b)
        env = shell_env._get_env_with_user_vars()

    assert _designes(env) == {str(venv_b)}
    assert os.path.samefile(os.getcwd(), projet_a)


def test_le_briefing_dit_quel_venv_les_commandes_utiliseront(tmp_path, registre_vide):
    projet_b, venv_b = _projet(tmp_path / "demo_application")
    sans_venv = tmp_path / "demo_ingestion"
    sans_venv.mkdir()
    (sans_venv / "pyproject.toml").write_text("[project]\nname='i'\n", encoding="utf-8")
    nulle_part = tmp_path / "documents"
    nulle_part.mkdir()

    assert f"Venv : {venv_b} — tes commandes" in _load_project_config(str(projet_b))
    assert "aucun venv trouvé — Environment(action='venv')" in _load_project_config(str(sans_venv))
    assert "pas de pyproject.toml ici" in _load_project_config(str(nulle_part))
