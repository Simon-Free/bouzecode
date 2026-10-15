"""Le provisioning de venv d'un bac à sable, verrouillé sur les trois dégâts déjà payés.

1. GRAVER LE LIEN ROULANT. `pyvenv.cfg` note la version du jour de création et son `home`
   peut pointer le lien de série d'uv (`cpython-3.12-windows-…`). Le 2026-08-20 à 16:08 ce
   lien est passé de 3.12.12 à 3.12.13 : quatre jours plus tard uv jugeait le venv invalide
   et le DÉTRUISAIT (il ne met jamais un venv à jour). `.python-version` du dépôt vaut la
   SÉRIE `3.12`, donc chaque `uv venv` sans `--python` versionné réarme ce piège.
2. LE VENV FANTÔME. `uv venv` réussit toujours, `uv sync` peut échouer : il restait alors un
   `.venv` VIDE dans le worktree, et c'est le venv le plus PROCHE — tout `uv run` lancé de là
   le préférait au venv de base et mourait en `ModuleNotFoundError`. Mesuré sur le parc :
   deux venvs de worktree à 0 et 1 paquet, dont site-packages ne contenait que
   `_virtualenv.py`. L'outil disait « environnement INCHANGÉ » : vrai pour les variables,
   faux pour le disque.
3. LE DÉPÔT PRINCIPAL PERDU. Les deps editables relatives (`../repo`) n'existent pas depuis
   un worktree isolé, d'où le relinkage préalable — mais il n'a lieu que si `repo_root` est
   connu, et un agent lancé À LA MAIN n'a pas de ticket pour le porter. Il doit se déduire
   du dépôt lui-même.

Aucun mock : vrai `uv`, vrais dépôts git, vrais dossiers sur disque.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import worktrees

_PYPROJECT = """\
[project]
name = "projet-bac-a-sable"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [{deps}]

[tool.uv]
package = false
{extra}
"""


def _projet(dossier: Path, *, deps: str = "", extra: str = "") -> Path:
    """Un projet Python minimal. `package = false` : uv ne doit pas BUILDER le projet
    (ça demanderait un backend de build et donc le réseau) — on ne teste que le venv."""
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "pyproject.toml").write_text(_PYPROJECT.format(deps=deps, extra=extra),
                                            encoding="utf-8")
    return dossier


def _home_grave(venv: Path) -> str:
    for ligne in (venv / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace").splitlines():
        cle, _, valeur = ligne.partition("=")
        if cle.strip() == "home":
            return valeur.strip()
    return ""


@pytest.fixture()
def uv_present():
    if not shutil.which("uv"):  # pragma: no cover - uv absent de la machine
        pytest.skip("uv n'est pas installé : ce test provisionne un vrai venv")


def test_le_venv_provisionne_grave_une_version_patch_pas_le_lien_roulant(tmp_path, uv_present):
    """Le dégât du 2026-08-24 naît à la CRÉATION, pas à la lecture : un `home` qui pointe la
    série (`cpython-3.12-…`) devient faux au prochain patch d'uv, et uv supprime alors le
    venv. On épingle donc la version PATCH, même quand `.python-version` dit la série."""
    projet = _projet(tmp_path / "projet")
    (projet / ".python-version").write_text("3.12\n", encoding="utf-8")  # le piège, tel quel

    assert worktrees._setup_venv(projet) == worktrees.VENV_OK

    home = _home_grave(projet / ".venv")
    if "cpython-" not in home:  # pragma: no cover - interpréteur système, pas un uv managé
        pytest.skip(f"interpréteur hors uv, aucune version dans le chemin : {home}")
    assert re.search(r"cpython-\d+\.\d+\.\d+", Path(home).name), (
        f"`home` pointe encore un lien de série, il sera périmé au prochain patch : {home}")


def test_un_sync_echoue_ne_laisse_pas_un_venv_fantome(tmp_path, monkeypatch, uv_present):
    """Un `.venv` vide est PIRE que pas de venv : il masque celui du dépôt de base pour tout
    `uv run` lancé depuis ce dossier. Un échec doit donc ne rien laisser sur le disque."""
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction
    autoriser_la_destruction(monkeypatch)
    # Dépendance introuvable par un CHEMIN local : uv échoue tout de suite, sans réseau.
    projet = _projet(tmp_path / "projet", deps='"paquet-absent"',
                     extra='\n[tool.uv.sources]\npaquet-absent = { path = "../paquet-absent" }\n')

    assert worktrees._setup_venv(projet) == worktrees.VENV_FAILED
    assert not (projet / ".venv").exists(), "le venv fantôme d'un sync échoué a survécu"


def _depot_git(racine: Path) -> Path:
    racine.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=racine, check=True,
                   capture_output=True)
    (racine / "fichier.txt").write_text("contenu", encoding="utf-8")
    subprocess.run(["git", "add", "fichier.txt"], cwd=racine, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                   cwd=racine, check=True, capture_output=True)
    return racine


def test_le_depot_principal_se_deduit_du_worktree_sans_ticket(tmp_path):
    """Sans ticket (agent lancé à la main), `repo_root` arrivait VIDE et le relinkage des
    sources editables était sauté. Le dépôt principal est pourtant écrit dans le worktree
    lui-même : git sait le dire."""
    depot = _depot_git(tmp_path / "depot")
    bac = tmp_path / "bac"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "agent/x", str(bac)],
                   cwd=depot, check=True, capture_output=True)

    trouve = worktrees.main_repo_root(bac)

    assert trouve, "le dépôt principal n'a pas été déduit du worktree"
    assert Path(trouve).resolve() == depot.resolve()


def test_hors_depot_git_le_depot_principal_reste_vide(tmp_path):
    """On ne devine pas : pas de dépôt, pas de repo_root (et donc pas de relinkage hasardeux)."""
    ailleurs = tmp_path / "pas_un_depot"
    ailleurs.mkdir()

    assert worktrees.main_repo_root(ailleurs) == ""


# ---------------------------------------------------------------------------
# Correctif D : le LANCEUR DE TESTS non plus ne fabrique pas de venv fantome.
# Mesure du 2026-09-09 dans un worktree d'agent :
#   uv run --no-sync --directory <worktree> pytest
#   -> "Creating virtual environment at: .venv" puis "error: Failed to spawn: pytest"
# Le .venv vide reste sur le disque, devient le venv le PLUS PROCHE, et shadow le venv
# de base pour tout appel suivant depuis ce dossier. Un simple RunPythonTest suffisait
# donc a fabriquer les worktrees a zero paquet ou plus rien ne s'importe.
# ---------------------------------------------------------------------------


def _faux_venv(racine, avec_pytest):
    """Cree un venv de facade : pyvenv.cfg + Scripts/python.exe, pytest en option."""
    bin_dir = racine / ("Scripts" if sys.platform == "win32" else "bin")
    bin_dir.mkdir(parents=True)
    (racine / "pyvenv.cfg").write_text("home = quelque part\n", encoding="utf-8")
    exe = "python.exe" if sys.platform == "win32" else "python"
    (bin_dir / exe).write_text("", encoding="utf-8")
    if avec_pytest:
        (bin_dir / ("pytest.exe" if sys.platform == "win32" else "pytest")).write_text(
            "", encoding="utf-8")
    return racine


def test_un_venv_fantome_n_est_pas_pris_pour_un_environnement_pret(tmp_path):
    """Le seul critere qui distingue « environnement pret » de « coquille vide » est la
    presence d'un pytest EXECUTABLE. Un .venv cree mais jamais peuple n'en a pas."""
    from bouzecode.backend.tools.ops import test_runner

    fantome = _faux_venv(tmp_path / "fantome", avec_pytest=False)
    pret = _faux_venv(tmp_path / "pret", avec_pytest=True)

    assert test_runner._venv_has_pytest(fantome) is False
    assert test_runner._venv_has_pytest(pret) is True


def test_un_venv_de_projet_peuple_est_execute_sans_uv(tmp_path):
    """Quand le projet a un vrai venv, son python est EXECUTE : `uv run` le synchroniserait
    (venv partage de demoapp_clone casse le 2026-10-14)."""
    from bouzecode.backend.tools.ops import test_runner

    projet = tmp_path / "projet"
    _faux_venv(projet / ".venv", avec_pytest=True)

    direct = test_runner._python_without_uv(projet, {})
    assert direct is not None and Path(direct).parent.parent == projet / ".venv"


def test_un_venv_de_projet_vide_ne_passe_plus_par_uv_run(tmp_path):
    """LE BUG : .venv vide dans le worktree + un venv de base porteur de pytest.
    On doit renvoyer le python du venv de BASE (on l'EXECUTE), jamais laisser uv en
    creer un autre. On ne le DESIGNE pas a uv non plus : `venv_env.is_compatible`
    interdit UV_PROJECT_ENVIRONMENT, uv detruirait ce venv le jour ou il le jugerait
    invalide."""
    from bouzecode.backend.tools.ops import test_runner

    projet = tmp_path / "projet"
    _faux_venv(projet / ".venv", avec_pytest=False)   # la coquille laissee par uv
    base = _faux_venv(tmp_path / "base", avec_pytest=True)

    direct = test_runner._python_without_uv(projet, {"VIRTUAL_ENV": str(base)})

    assert direct is not None
    assert Path(direct).parent.parent == base          # bien le venv de BASE
    assert Path(direct).is_file()
