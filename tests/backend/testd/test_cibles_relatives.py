# [desc] RunPythonTest : une cible relative se lit depuis le dossier de l'agent, quel que soit le projet où pytest tourne, par le démon (wait true ou false) comme en direct ; une cible introuvable est refusée en le disant [/desc]
"""Session de4d1304 (2026-10-14), job 246a5fe8 : `targets=['tests/focus/…']` alors que le
dossier de l'agent était encore `worktrees\\demo\\solo-10` (pas `demo_application`). La
cible n'existait pas là ; pytest a tourné quand même, dans ce mauvais dossier et avec le venv de
bouzecode, et le modèle a lu « file or directory not found » comme une panne de l'outil. Ce n'était
pas `wait=false` : le run suivant (`wait=true`) venait après un `LoadProjectConfig(cd=true)`."""
from __future__ import annotations

import re

import pytest

from bouzecode.backend.core.dossier_agent import Atelier, dans
from bouzecode.backend.testd.rendu import statut_job
from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.backend.testd.aides import projet

_DEUX = {"tests/test_deux.py": "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n"}


def _projet(racine):
    (racine / "tests").mkdir(parents=True)
    return projet(racine, _DEUX)


def _jusqu_au_bout(rendu: str) -> str:
    job_id = re.search(r"job (\w+) ", rendu).group(1)
    statut = statut_job(job_id, wait_s=60)
    while "terminé" not in statut:
        statut = statut_job(job_id, wait_s=60)
    return statut


@pytest.mark.parametrize("attendre", [True, False])
def test_cible_relative_au_dossier_de_l_agent_par_le_demon(demon, tmp_path, attendre):
    _projet(tmp_path / "p")  # le cwd du test (= dossier de l'agent) est tmp_path
    rendu = run_python_test(targets=["p/tests/test_deux.py"], parallel="off", wait=attendre)
    rendu = rendu if attendre else _jusqu_au_bout(rendu)
    assert "2 passed" in rendu, rendu


def test_cible_relative_au_dossier_de_l_agent_en_direct(tmp_path, monkeypatch):
    monkeypatch.setenv("BZ_TESTD", "0")
    _projet(tmp_path / "p")
    rendu = run_python_test(targets=["p/tests/test_deux.py"], parallel="off")
    assert "2 passed" in rendu, rendu


def test_cible_relative_dans_l_atelier_d_un_sous_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("BZ_TESTD", "0")
    racine = _projet(tmp_path / "p")
    with dans(Atelier(dossier=str(racine))):
        rendu = run_python_test(targets=["tests/test_deux.py"], parallel="off")
    assert "2 passed" in rendu, rendu


@pytest.mark.parametrize("attendre", [True, False])
def test_cible_introuvable_depuis_le_dossier_de_l_agent_est_refusee(demon, tmp_path, attendre):
    _projet(tmp_path / "demo_application")
    mauvais = projet(tmp_path / "demo", {})  # le dossier de l'agent, sans cette cible
    with dans(Atelier(dossier=str(mauvais))):
        rendu = run_python_test(targets=["tests/test_deux.py"], parallel="off", wait=attendre)
    assert rendu.startswith("Error: cible introuvable"), rendu
    assert str(mauvais) in rendu and "job" not in rendu, rendu
    assert not (tmp_path / "testd_home" / "jobs").exists() or not any(
        (tmp_path / "testd_home" / "jobs").iterdir())


def test_motif_de_cibles_developpe_depuis_le_dossier_de_l_agent(tmp_path, monkeypatch):
    """Session dee74ecf8286 (B4) : `tests/test_demoapp_rules*.py` était refusé comme introuvable."""
    monkeypatch.setenv("BZ_TESTD", "0")
    racine = _projet(tmp_path / "p")
    (racine / "tests" / "test_trois.py").write_text("def test_c():\n    assert True\n", encoding="utf-8")
    with dans(Atelier(dossier=str(racine))):
        rendu = run_python_test(targets=["tests/test_*.py"], parallel="off")
        vide = run_python_test(targets=["tests/test_aucun*.py"], parallel="off")
    assert "3 passed" in rendu, rendu
    assert vide.startswith("Error: cible introuvable : tests/test_aucun*.py"), vide
