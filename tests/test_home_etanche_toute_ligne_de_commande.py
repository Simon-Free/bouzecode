# [desc] Le HOME est isolé quelle que soit la ligne pytest (-o addopts="", --noconftest, test hors du dépôt, pytest.main d'un script) ; les écrivains du store refusent le vrai ~/.bouzecode sous pytest. [/desc]
"""Fuites du 2026-10-06 dans le vrai profil : `remote/executions/100.json` (suite lancée avec
`-o addopts=""` sur une branche sans conftest racine) puis `web_v2/projects.json` ÉCRASÉ (fichier
de test hors du dépôt, donc sans conftest ni addopts). Le « vrai HOME » d'un pytest imbriqué est
ici un dossier jetable : exactement la situation réelle, sans jamais toucher au profil."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.backend.core.garde_vrai_home import EcritureDansLeVraiHome
from bouzecode.remote import registre
from bouzecode.web_v2.services.work import _store_connection, projects
from tests.pytest_imbrique import options_etanches

RACINE = Path(__file__).resolve().parent.parent
TIMEOUT_S = 120

#  Le geste exact de `temp_test_reel_clone.py` (registre écrit à la main) et celui de la suite
#  sur faux Rundeck (fiche d'exécution), depuis un fichier de test qui n'est PAS dans le dépôt.
TEST_FAUTIF = '''
import json
from pathlib import Path

from bouzecode.remote import registre
from bouzecode.web_v2.services.work import projects


def test_ecrit_le_registre_et_une_fiche():
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": "x", "path": "y"}]), encoding="utf-8")
    projects._save([{"slug": "x", "name": "x", "path": "y"}])
    registre.enregistrer("100", {"job_id": "job-1"})
    assert not str(projects.PROJECTS_PATH).startswith(VRAI)
    assert not str(registre.racine_locale()).startswith(VRAI)
'''

SCRIPT_PYTEST_MAIN = '''
import sys
import pytest
sys.exit(pytest.main(sys.argv[1:]))
'''


def _pytest_avec_un_vrai_home(home: Path, dossier: Path, *commande: str) -> subprocess.CompletedProcess:
    """pytest HORS de toute isolation héritée : le vrai HOME du sous-processus est `home`."""
    env = {k: v for k, v in os.environ.items() if k != "BZ_TESTS_VRAI_HOME" and not k.startswith("PYTEST_")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONPATH=str(RACINE / 'src'),
               PYTHONIOENCODING="utf-8", BOUZECODE_WAKE_POLLER="0")
    return subprocess.run([sys.executable, *commande], cwd=str(dossier), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)


def _cas(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "vrai_home"
    home.mkdir()
    dossier = tmp_path / "hors_du_depot"
    dossier.mkdir()
    cible = dossier / "test_fautif.py"
    cible.write_text(f"VRAI = {str(home)!r}\n" + TEST_FAUTIF, encoding="utf-8")
    return home, dossier, cible


@pytest.mark.parametrize("options", [["-o", "addopts="], ["--noconftest", "-p", "no:randomly"], []],
                         ids=["addopts-vide", "noconftest", "sans-option"])
def test_un_test_hors_du_depot_n_ecrit_pas_dans_le_vrai_home(tmp_path, options):
    home, dossier, cible = _cas(tmp_path)
    fini = _pytest_avec_un_vrai_home(home, dossier, "-m", "pytest", str(cible), "-q", "-p", "no:xdist",
                                     *options_etanches(dossier), *options)
    assert fini.returncode == 0, fini.stdout + fini.stderr
    assert not (home / ".bouzecode").exists(), sorted(map(str, (home / ".bouzecode").rglob("*")))


def test_pytest_main_d_un_script_n_ecrit_pas_dans_le_vrai_home(tmp_path):
    home, dossier, cible = _cas(tmp_path)
    script = dossier / "lance.py"
    script.write_text(SCRIPT_PYTEST_MAIN, encoding="utf-8")
    fini = _pytest_avec_un_vrai_home(home, dossier, str(script), str(cible), "-q", "-p", "no:xdist",
                                     "-o", "addopts=", *options_etanches(dossier))
    assert fini.returncode == 0, fini.stdout + fini.stderr
    assert not (home / ".bouzecode").exists(), sorted(map(str, (home / ".bouzecode").rglob("*")))


@pytest.fixture()
def vrai_home_simule(tmp_path, monkeypatch):
    """Le « vrai HOME » vu du garde devient un dossier jetable : un garde cassé écrirait ICI."""
    monkeypatch.setenv("BZ_TESTS_VRAI_HOME", str(tmp_path))
    return tmp_path / ".bouzecode"


def test_le_registre_des_projets_refuse_le_vrai_home(vrai_home_simule, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_PATH", vrai_home_simule / "web_v2" / "projects.json")
    with pytest.raises(EcritureDansLeVraiHome, match="projects.json"):
        projects._save([{"slug": "x", "name": "x", "path": "y"}])
    assert not vrai_home_simule.exists()


def test_le_store_des_tickets_et_signalements_refuse_le_vrai_home(vrai_home_simule):
    with pytest.raises(EcritureDansLeVraiHome, match="tickets.db"):
        _store_connection.connection(vrai_home_simule / "web_v2" / "tickets" / "tickets.db")
    assert not vrai_home_simule.exists()


def test_le_registre_des_executions_distantes_refuse_le_vrai_home(vrai_home_simule, monkeypatch):
    for nom in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(nom, str(vrai_home_simule.parent))
    with pytest.raises(EcritureDansLeVraiHome, match="remote"):
        registre.enregistrer("100", {"job_id": "job-1"})
    assert not vrai_home_simule.exists()
