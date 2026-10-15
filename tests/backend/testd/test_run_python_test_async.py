# [desc] testd, du point de vue du modèle : RunPythonTest(wait=false) rend un job_id, TestStatus le suit jusqu'au rapport compact ; wait=true passe par la file et montre l'avancement [/desc]
from __future__ import annotations

import re

from bouzecode.backend.testd.rendu import statut_job
from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.backend.testd.aides import projet

_DEUX = {"test_deux.py": "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n"}


def test_wait_false_puis_teststatus(demon, tmp_path):
    racine = projet(tmp_path / "p", _DEUX)
    rendu = run_python_test(targets=[str(racine / "test_deux.py")], parallel="off", wait=False)
    job_id = re.search(r"job (\w+) ", rendu).group(1)
    assert "TestStatus" in rendu

    statut = statut_job(job_id, wait_s=60)
    while "terminé" not in statut:
        statut = statut_job(job_id, wait_s=60)
    assert "2 passed" in statut


def test_wait_true_passe_par_la_file(demon, tmp_path):
    racine = projet(tmp_path / "p", _DEUX)
    lignes = []
    rendu = run_python_test(targets=[str(racine / "test_deux.py")], parallel="2",
                            progression=lignes.append)
    assert "testd job" in rendu and "2 passed" in rendu
    assert any(l.startswith("pytest: ") for l in lignes)


def test_sans_demon_le_chemin_direct_reste(tmp_path, monkeypatch):
    monkeypatch.setenv("BZ_TESTD", "0")
    racine = projet(tmp_path / "p", _DEUX)
    rendu = run_python_test(targets=[str(racine / "test_deux.py")], parallel="off")
    assert "testd" not in rendu and "2 passed" in rendu
