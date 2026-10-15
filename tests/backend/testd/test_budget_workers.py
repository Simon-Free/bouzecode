# [desc] testd : `-n` choisi par job (pas de xdist pour un petit run, borné par le budget de workers de la machine, worksteal), durées gardées par dépôt et fichiers les plus longs d'abord [/desc]
from __future__ import annotations

import os
import re

from bouzecode.backend.testd.budget.durations import workers_voulus
from bouzecode.backend.testd.rendu import attendre
from tests.backend.testd.aides import commande, projet


def test_petit_run_sans_xdist_gros_run_borne_par_les_fichiers():
    huit = [f"t{i}.py::test_x" for i in range(8)]
    assert workers_voulus(huit, {}, 4) == 0                      # 8 tests inconnus : ~4 s
    assert workers_voulus(huit, {n: 3.0 for n in huit}, 4) == 4  # 24 s mesurées, 8 fichiers
    trente = [f"t{i % 2}.py::test_{i}" for i in range(30)]
    assert workers_voulus(trente, {}, 4) == 2                    # 2 fichiers seulement
    assert workers_voulus(trente, {}, 0) == 0                    # parallel='off' respecté


def test_un_fichier_a_tests_lourds_prend_un_worker_par_test_lourd():
    """Job 29367671 (B4) : 8 tests d'un fichier dont 2 lourds (37 et 9 s) joués en série ; un
    test navigateur jamais mesuré compte 10 s, et `-n 1` n'existe pas (0 : sans xdist)."""
    exos = [f"tests/test_exo.py::test_{i}" for i in range(8)]
    mesurees = {**{n: 0.02 for n in exos}, exos[0]: 36.9, exos[1]: 8.7}
    assert workers_voulus(exos, mesurees, 4) == 2
    assert workers_voulus(exos[:3], {}, 4, navigateur=True) == 3     # 3 inconnus = ~30 s
    assert workers_voulus(exos[:1], {}, 4, navigateur=True) == 0     # 1 seul : pas de xdist
    assert workers_voulus(exos[:3], {}, 4) == 0                      # hors navigateur : ~1,5 s


def _sortie(etat) -> str:
    return "\n".join(open(p["output"], encoding="utf-8").read() for p in etat["parts"])


def test_budget_de_la_machine_borne_le_n_et_worksteal(demon, tmp_path, monkeypatch):
    monkeypatch.setenv("BZ_TESTD_WORKERS_TOTAL", "2")
    corps = "".join(f"def test_{i}():\n    assert True\n" for i in range(8))
    racine = projet(tmp_path / "p", {f"test_f{n}.py": corps for n in range(3)})
    job = demon.soumettre(commande("test_f0.py", "test_f1.py", "test_f2.py", workers=4),
                          dict(os.environ), str(racine), 120, "")
    etat = attendre(job["job_id"], 120, au_premier_echec=False)
    assert etat["passed"] == 24 and etat["workers"] == 2, etat
    assert "-n 2 au lieu de 3" in etat["notes"] and "2/2 workers" in etat["notes"]
    assert "created: 2/2 workers" in _sortie(etat)
    assert "WorkStealingScheduling" in _sortie(etat)


def test_durees_gardees_et_fichier_le_plus_long_d_abord(demon, tmp_path):
    racine = projet(tmp_path / "p", {
        "test_a_court.py": "def test_court():\n    assert True\n",
        "test_z_long.py": "import time\ndef test_long():\n    time.sleep(1.5)\n",
    })
    ordres = []
    for _ in range(2):
        job = demon.soumettre(commande("test_a_court.py", "test_z_long.py"), dict(os.environ),
                              str(racine), 60, "")
        etat = attendre(job["job_id"], 60, au_premier_echec=False)
        ordres.append(re.findall(r"(test_\w+)\.py::\w+ PASSED", _sortie(etat)))
    assert ordres[0] == ["test_a_court", "test_z_long"]
    assert ordres[1] == ["test_z_long", "test_a_court"]
    durees = (tmp_path / "test_durations").glob("*.json")
    contenu = next(durees).read_text(encoding="utf-8")
    assert "test_z_long.py::test_long" in contenu
