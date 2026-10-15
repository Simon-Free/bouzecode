# [desc] testd + sélection : un run full passé par le démon (wait=false) compare ses échecs à la base dans le créneau du job, et TestStatus rend NEW / pre-existing ; le plugin de sélection survit au retour immédiat [/desc]
from __future__ import annotations

import re
import subprocess

from bouzecode.backend.testd.rendu import statut_job
from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.backend.tools.runner.test_comparaison_base import _FICHIERS, _section


def _git(depot, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=depot,
                   check=True, capture_output=True)


def _depot(racine):
    """develop : un test déjà rouge ; la branche casse test_f."""
    for nom, contenu in _FICHIERS.items():
        (racine / nom).parent.mkdir(parents=True, exist_ok=True)
        (racine / nom).write_text(contenu, encoding="utf-8")
    _git(racine, "init", "-q", "-b", "develop")
    _git(racine, "add", ".")
    _git(racine, "commit", "-q", "-m", "base")
    _git(racine, "checkout", "-q", "-b", "travail")
    (racine / "src/pkg/a.py").write_text("def f():\n    return 2\n")
    _git(racine, "commit", "-q", "-am", "travail")
    return racine


def test_full_par_le_demon_compare_a_la_base(demon, tmp_path, monkeypatch):
    racine = _depot(tmp_path / "depot")
    monkeypatch.chdir(racine)
    monkeypatch.setenv("BZ_NIGHTLY", "1")  # full=true : le chemin du build nightly
    rendu = run_python_test(full=True, parallel="off", wait=False, timeout=120)
    job_id = re.search(r"job (\w+) ", rendu).group(1)
    statut = statut_job(job_id, wait_s=120)
    while "terminé" not in statut:
        statut = statut_job(job_id, wait_s=120)
    assert _section(statut, "NEW failures") == ["tests/test_ok.py::test_f"], statut
    assert _section(statut, "pre-existing on base develop") == [
        "tests/test_ancien.py::test_rouge_sur_develop"], statut
    assert "2 failed" in statut, statut
