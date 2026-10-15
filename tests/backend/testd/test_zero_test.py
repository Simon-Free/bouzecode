# [desc] RunPythonTest : un run où AUCUN test ne tourne le dit — verdict de pytest, ce qui a désélectionné (addopts du projet), l'appel qui les lance — par le démon (aucun sous-run lancé à vide) comme en direct [/desc]
"""Session de4d1304 (2026-10-14), jobs 1c757948, 396e7ca4, f2f9e3ac, 51aeb8bb : le pyproject de
demo_application porte `addopts = "-m 'not llm and not network'"`, les tests ciblés étaient
`network`. Le rapport ne contenait que l'en-tête : le modèle a contourné l'outil 6 fois."""
from __future__ import annotations

import re

import pytest

from bouzecode.backend.testd.rendu import statut_job
from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.backend.testd.aides import projet

_RESEAU = {
    "pyproject.toml": """
        [project]
        name = "jetable"
        version = "0"
        [tool.pytest.ini_options]
        addopts = "-m 'not network'"
        markers = ["network: atteint la base"]
    """,
    "test_reseau.py": """
        import pytest
        pytestmark = pytest.mark.network
        def test_lit_la_base():
            assert True
        def test_ecrit_la_base():
            assert True
    """,
}


def _rapport(rendu: str, attendre: bool) -> str:
    if attendre:
        return rendu
    job_id = re.search(r"job (\w+) ", rendu).group(1)
    statut = statut_job(job_id, wait_s=60)
    while "terminé" not in statut:
        statut = statut_job(job_id, wait_s=60)
    return statut


@pytest.mark.parametrize("parallel,attendre", [("off", True), ("2", False)])
def test_zero_test_par_le_demon_dit_pourquoi_et_comment(demon, tmp_path, parallel, attendre):
    racine = projet(tmp_path / "p", _RESEAU)
    rendu = _rapport(run_python_test(targets=[str(racine / "test_reseau.py")], parallel=parallel,
                                     wait=attendre), attendre)
    assert re.search(r"verdict de pytest : « .*2 deselected.* in [\d.]+s »", rendu), rendu
    assert ("0 test lancé : 2 désélectionné(s) par -m 'not network' (addopts du projet, "
            "pyproject.toml). Marqueurs des tests écartés : network ×2.") in rendu, rendu
    assert "Pour les lancer : marker='network'" in rendu, rendu
    # La collecte a tout écarté : aucun sous-run n'est lancé à vide.
    job = next((tmp_path / "testd_home" / "jobs").iterdir())
    assert not list(job.glob("*.txt")), list(job.iterdir())

    relance = run_python_test(targets=[str(racine / "test_reseau.py")], parallel="off",
                              marker="network")
    assert "2 passed" in relance and "0 test lancé" not in relance, relance


def test_zero_test_en_direct(tmp_path, monkeypatch):
    monkeypatch.setenv("BZ_TESTD", "0")
    racine = projet(tmp_path / "p", _RESEAU)
    rendu = run_python_test(targets=[str(racine / "test_reseau.py")], parallel="off")
    assert "verdict de pytest : « 2 deselected in " in rendu, rendu
    assert "0 test lancé : 2 désélectionné(s) par -m 'not network' (addopts du projet" in rendu, rendu
    assert "marker='network'" in rendu, rendu


def test_fichier_sans_test_le_dit(demon, tmp_path):
    racine = projet(tmp_path / "p", {"test_vide.py": "UNE_CONSTANTE = 1\n"})
    rendu = run_python_test(targets=[str(racine / "test_vide.py")], parallel="off")
    assert "verdict de pytest : « no tests collected in " in rendu, rendu
    assert "0 test lancé, aucun désélectionné : rien n'a été collecté" in rendu, rendu
