# [desc] testd : un worktree est préchauffé (fichiers suivis + paquets importés du venv) une seule fois par (dossier, HEAD), dès la soumission d'un job, sans retarder le job [/desc]
from __future__ import annotations

import os
import subprocess
import sys
import time

from bouzecode.backend.testd.common import sans_fenetre
from bouzecode.backend.testd.rendu import attendre
from bouzecode.backend.testd.warm.prechauffage import Prechauffage
from tests.backend.testd.aides import commande, projet


def _git(racine, *args) -> None:
    subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True, timeout=60,
                   **sans_fenetre())


def _depot(racine):
    projet(racine, {"test_a.py": "import pytest\n\ndef test_a():\n    assert True\n"})
    _git(racine, "init", "-q")
    _git(racine, "add", "pyproject.toml", "test_a.py")
    _git(racine, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return racine


def test_prechauffage_une_fois_par_dossier_et_head(tmp_path):
    """Même dossier, même HEAD : une seule passe ; un nouveau commit ou un autre dossier en refont une.
    La passe lit les fichiers suivis et le paquet `pytest` importé, pris dans le venv."""
    depot = _depot(tmp_path / "depot")
    prechauffage = Prechauffage()
    for _ in range(3):
        prechauffage.demander(str(depot), sys.executable).join(60)
    assert len(prechauffage.passes) == 1
    passe = prechauffage.passes[0]
    assert passe["fichiers"] == 2 and passe["fichiers_venv"] > 0, passe

    (depot / "test_b.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")
    _git(depot, "add", "test_b.py")
    _git(depot, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "b")
    prechauffage.demander(str(depot), sys.executable).join(60)
    autre = _depot(tmp_path / "autre")
    prechauffage.demander(str(autre), sys.executable).join(60)
    assert [p["fichiers"] for p in prechauffage.passes] == [2, 3, 2]

    prechauffage.demander(str(tmp_path / "pas_un_depot"), sys.executable).join(60)
    assert len(prechauffage.passes) == 3


def test_le_demon_prechauffe_le_worktree_du_premier_job_seulement(demon, tmp_path):
    """Deux jobs dans le même worktree : les deux passent, le journal du démon montre une seule passe."""
    depot = _depot(tmp_path / "depot")
    for _ in range(2):
        job = demon.soumettre(commande("test_a.py"), dict(os.environ), str(depot), 120, sys.executable)
        etat = attendre(job["job_id"], 120, au_premier_echec=False)
        assert (etat["passed"], etat["failed"]) == (1, 0), etat
    journal = tmp_path / "testd_home" / "daemon.log"   # encodage local du journal : on lit des octets
    fin = time.monotonic() + 30
    while b"chauffage {" not in journal.read_bytes() and time.monotonic() < fin:
        time.sleep(0.2)
    assert journal.read_bytes().count(b"chauffage {") == 1
