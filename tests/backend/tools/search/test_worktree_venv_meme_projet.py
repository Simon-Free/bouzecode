"""Un worktree n'emprunte QUE le venv de son propre projet, jamais celui qui fait tourner bouzecode.

Dégât du 2026-10-12 (11:48 et 14:40) : un sous-agent TUI dans un worktree de
demo_application (3.13) a reçu `sys.prefix` = le venv de bouzecode (bouzecode, 3.12) comme
UV_PROJECT_ENVIRONMENT ; son `uv sync --extra dev` a vidé ce venv partagé, deux fois.
"""
import os
import subprocess
import sys

from bouzecode.backend.tools.ops import venv_du_projet, venv_meme_projet
from bouzecode.backend.tools.ops.shell_env import worktree_child_env
from bouzecode.web_v2.runtime import venv_env

BIN = "Scripts" if os.name == "nt" else "bin"


def _venv(dossier):
    (dossier / BIN).mkdir(parents=True)
    (dossier / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return dossier


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


def _depot(racine, sous_dossier=""):
    projet = racine / sous_dossier if sous_dossier else racine
    projet.mkdir(parents=True)
    (projet / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", cwd=racine)
    _git("add", os.path.relpath(projet / "pyproject.toml", racine), cwd=racine)
    _git("commit", "-q", "-m", "init", cwd=racine)
    return racine


def _worktree(depot, ou):
    _git("worktree", "add", "-q", "-b", ou.name, str(ou), cwd=depot)
    return ou


def _bouzecode_tourne_depuis(monkeypatch, venv):
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "base_prefix", str(venv.parent / "interpreteur"))


def _designes(env):
    return {env.get("VIRTUAL_ENV", ""), env.get("UV_PROJECT_ENVIRONMENT", "")} - {""}


def test_un_worktree_du_projet_b_recoit_le_venv_de_b_pas_celui_de_bouzecode(tmp_path, monkeypatch):
    venv_bouzecode = _venv(tmp_path / "bouzecode" / ".venv")
    _bouzecode_tourne_depuis(monkeypatch, venv_bouzecode)
    depot_b = _depot(tmp_path / "demo_application")
    venv_b = _venv(depot_b / ".venv")
    wt = _worktree(depot_b, tmp_path / "worktrees" / "tui-1")

    out = worktree_child_env({"BOUZECODE_WORKTREE_ROOT": str(wt), "PATH": "/usr/bin"})

    assert _designes(out) == {str(venv_b)}
    assert str(venv_bouzecode) not in out["PATH"]


def test_sans_venv_du_meme_projet_aucun_venv_n_est_designe(tmp_path, monkeypatch):
    venv_bouzecode = _venv(tmp_path / "bouzecode" / ".venv")
    _bouzecode_tourne_depuis(monkeypatch, venv_bouzecode)
    wt = _worktree(_depot(tmp_path / "demo_application"), tmp_path / "worktrees" / "tui-2")

    out = worktree_child_env({"BOUZECODE_WORKTREE_ROOT": str(wt), "PATH": "/usr/bin"})

    assert _designes(out) == set()
    assert out["UV_NO_SYNC"] == "1"


def test_le_venv_de_bouzecode_herite_est_retire_et_remplace(tmp_path, monkeypatch):
    """Un TUI lancé depuis un venv activé (ou un agent parent d'un autre projet) transmet
    VIRTUAL_ENV / UV_PROJECT_ENVIRONMENT / PATH : dans le worktree de B, ils sont retirés."""
    venv_bouzecode = _venv(tmp_path / "bouzecode" / ".venv")
    _bouzecode_tourne_depuis(monkeypatch, venv_bouzecode)
    depot_b = _depot(tmp_path / "demo_application")
    venv_b = _venv(depot_b / ".venv")
    wt = _worktree(depot_b, tmp_path / "worktrees" / "tui-3")
    bin_bouzecode = str(venv_bouzecode / BIN)
    env = {"BOUZECODE_WORKTREE_ROOT": str(wt), "VIRTUAL_ENV": str(venv_bouzecode),
           "UV_PROJECT_ENVIRONMENT": str(venv_bouzecode), "PATH": os.pathsep.join([bin_bouzecode, "/usr/bin"])}

    out = worktree_child_env(env)

    assert _designes(out) == {str(venv_b)}
    assert bin_bouzecode not in out["PATH"].split(os.pathsep)


def test_un_worktree_de_bouzecode_lui_meme_garde_le_venv_de_bouzecode(tmp_path, monkeypatch):
    depot_bouzecode = _depot(tmp_path / "bouzecode")
    venv_bouzecode = _venv(depot_bouzecode / ".venv")
    _bouzecode_tourne_depuis(monkeypatch, venv_bouzecode)
    wt = _worktree(depot_bouzecode, tmp_path / "worktrees" / "bz-1")

    out = worktree_child_env({"BOUZECODE_WORKTREE_ROOT": str(wt), "PATH": "/usr/bin"})

    assert _designes(out) == {str(venv_bouzecode)}


def test_un_projet_en_sous_dossier_trouve_le_venv_a_la_meme_position(tmp_path):
    depot = _depot(tmp_path / "mono", sous_dossier="appli")
    venv_appli = _venv(depot / "appli" / ".venv")
    wt = _worktree(depot, tmp_path / "worktrees" / "mono-1")

    assert venv_du_projet.venv_du_projet(str(wt / "appli" / "src")) == str(venv_appli)


def test_le_depot_principal_se_lit_sur_le_disque(tmp_path):
    depot = _depot(tmp_path / "projet")
    wt = _worktree(depot, tmp_path / "worktrees" / "lu")
    assert os.path.samefile(venv_meme_projet.depot_principal(str(wt)), depot)
    assert os.path.samefile(venv_meme_projet.depot_principal(str(depot)), depot)
    assert venv_meme_projet.depot_principal(str(tmp_path)) == ""


def test_hors_worktree_le_venv_de_bouzecode_n_est_designe_que_dans_son_projet(tmp_path, monkeypatch):
    """Depuis le 2026-10-12 (soir) : hors projet, le venv de bouzecode est retiré en entier (plus
    seulement UV_PROJECT_ENVIRONMENT) ; dans le projet de bouzecode, c'est SON venv qui est désigné."""
    projet_bouzecode = tmp_path / "bouzecode"
    venv_bouzecode = _venv(projet_bouzecode / ".venv")
    (projet_bouzecode / "pyproject.toml").write_text("[project]\nname='bouzecode'\n", encoding="utf-8")
    _bouzecode_tourne_depuis(monkeypatch, venv_bouzecode)
    env = {"UV_PROJECT_ENVIRONMENT": str(venv_bouzecode), "PATH": "/usr/bin"}
    ailleurs = tmp_path / "demo_application"
    ailleurs.mkdir()

    assert _designes(worktree_child_env(env, dossier=str(ailleurs))) == set()
    assert _designes(worktree_child_env(env, dossier=str(projet_bouzecode))) == {str(venv_bouzecode)}


def test_le_venv_dedie_se_cree_sans_aucun_venv_herite(tmp_path):
    """`Environment(action='venv')` : `uv venv` / `uv sync` ne doivent viser que `./.venv`."""
    herite = str(tmp_path / "bouzecode" / ".venv")
    env = {"VIRTUAL_ENV": herite, "UV_PROJECT_ENVIRONMENT": herite, "UV_NO_SYNC": "1",
           "PATH": os.pathsep.join([os.path.join(herite, BIN), "/usr/bin"])}

    out = venv_env.env_sans_venv_designe(env)

    assert out == {"PATH": "/usr/bin"}
