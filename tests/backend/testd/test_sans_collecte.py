# [desc] testd : un petit job dont les fichiers sont déjà classés (chemin + mtime) saute la collecte navigateur / hors navigateur ; un fichier modifié, un dossier ou un gros job navigateur la refont [/desc]
"""Mesuré le 2026-10-14 : la collecte coûtait 5 à 8 s sur demoapp_clone à chaque job, soit tout le
gain du navigateur chaud sur un petit job."""
from __future__ import annotations

import os
import re

from bouzecode.backend.testd.budget.classes import memoriser, plan_sans_collecte
from bouzecode.backend.testd.rendu import statut_job
from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.backend.testd.aides import projet

_GROUPES = {"other": ["test_a.py::test_un", "test_a.py::test_deux"],
            "browser": ["test_nav.py::test_page"]}


def _fichiers(racine):
    return projet(racine, {"test_a.py": "def test_un():\n    pass\n\ndef test_deux():\n    pass\n",
                           "test_nav.py": "def test_page():\n    pass\n"})


def test_fichier_classe_hors_navigateur_saute_la_collecte(tmp_path):
    racine, historique = _fichiers(tmp_path / "p"), tmp_path / "depot.json"
    assert plan_sans_collecte(historique, str(racine), ["test_a.py"], {}) is None
    memoriser(historique, str(racine), _GROUPES, filtre=False)
    plan = plan_sans_collecte(historique, str(racine), [str(racine / "test_a.py")], {})
    assert plan == {"browser": False, "nodeids": []}


def test_fichier_modifie_dossier_ou_id_inconnu_refont_la_collecte(tmp_path):
    racine, historique = _fichiers(tmp_path / "p"), tmp_path / "depot.json"
    memoriser(historique, str(racine), _GROUPES, filtre=False)
    assert plan_sans_collecte(historique, str(racine), ["."], {}) is None
    assert plan_sans_collecte(historique, str(racine), ["test_autre.py"], {}) is None
    mtime = (racine / "test_a.py").stat().st_mtime
    os.utime(racine / "test_a.py", (mtime + 5, mtime + 5))
    assert plan_sans_collecte(historique, str(racine), ["test_a.py"], {}) is None


def test_navigateur_saute_la_collecte_seulement_si_petit(tmp_path):
    racine, historique = _fichiers(tmp_path / "p"), tmp_path / "depot.json"
    memoriser(historique, str(racine), _GROUPES, filtre=False)
    petit = plan_sans_collecte(historique, str(racine), ["test_nav.py"], {"test_nav.py::test_page": 2.0})
    assert petit == {"browser": True, "nodeids": ["test_nav.py::test_page"]}
    assert plan_sans_collecte(historique, str(racine), ["test_nav.py"],
                              {"test_nav.py::test_page": 30.0}) is None


def test_collecte_filtree_ne_retient_que_le_navigateur(tmp_path):
    """Sous `-k`/`-m`, un test navigateur a pu être écarté : « hors navigateur » n'est pas sûr."""
    racine, historique = _fichiers(tmp_path / "p"), tmp_path / "depot.json"
    memoriser(historique, str(racine), _GROUPES, filtre=True)
    assert plan_sans_collecte(historique, str(racine), ["test_a.py"], {}) is None
    assert plan_sans_collecte(historique, str(racine), ["test_nav.py"], {})["browser"] is True


def _job(rendu: str) -> str:
    job_id = re.search(r"job (\w+) ", rendu).group(1)
    statut = statut_job(job_id, wait_s=60)
    while "terminé" not in statut:
        statut = statut_job(job_id, wait_s=60)
    return statut


def test_second_job_sur_le_meme_fichier_saute_la_collecte(demon, tmp_path):
    racine = _fichiers(tmp_path / "p")
    cible = [str(racine / "test_a.py")]
    premier = _job(run_python_test(targets=cible, parallel="off", wait=False))
    assert "2 passed" in premier and "collecte sautée" not in premier, premier
    second = _job(run_python_test(targets=cible, parallel="off", wait=False))
    assert "2 passed" in second and "collecte sautée" in second, second
