# [desc] testd : au plus N jobs navigateur à la fois sur la machine (BZ_TESTD_BROWSER_JOBS) ; le job suivant attend son créneau, position visible, puis passe [/desc]
"""Session B4 (2026-10-14) : 4 sous-agents jouaient des tests navigateur en même temps, aucun
n'attendait (`queued_s = 0`), chacun allait 2 à 4 fois moins vite.

Le test navigateur tient son créneau jusqu'à ce que le test l'ait vu occupé (fichier de
libération), pas pendant un délai fixe : en `-n 4` chargé, la collecte du second job dépassait
les 5 s du `sleep` d'origine, le premier avait déjà rendu son créneau et l'attente n'était jamais
observée."""
from __future__ import annotations

import os
import time

from bouzecode.backend.testd.rendu import attendre, ligne_avancement
from tests.backend.testd.aides import commande, projet

_NAVIGATEUR = {
    "conftest.py": """
        def pytest_configure(config):
            config.addinivalue_line("markers", "browser: test navigateur")
    """,
    "test_ecran.py": """
        import os, time, pytest
        from pathlib import Path
        @pytest.mark.browser
        def test_parcours_de_l_ecran():
            liberation = Path(os.environ["BZ_TEST_LIBERATION"])
            fin = time.monotonic() + 120
            while not liberation.exists():
                assert time.monotonic() < fin, "créneau jamais libéré par le test"
                time.sleep(0.1)
    """,
    #  Le test tient son créneau aussi longtemps que la machine chargée le demande.
    ".bouzecode/tests.yaml": "timeouts:\n  per_test_browser: 0\n",
}


def _projet(racine):
    (racine / ".bouzecode").mkdir(parents=True)
    return projet(racine, _NAVIGATEUR)


def test_second_job_navigateur_attend_son_creneau(demon, tmp_path, monkeypatch):
    """Deux jobs navigateur avec un seul créneau : le second attend, sa position est visible,
    puis les deux passent."""
    liberation = tmp_path / "liberer"
    monkeypatch.setenv("BZ_TEST_LIBERATION", str(liberation))
    monkeypatch.setenv("BZ_TESTD_WORKERS_TOTAL", "4")
    monkeypatch.setenv("BZ_TESTD_BROWSER_JOBS", "1")
    premier = demon.soumettre(commande("test_ecran.py"), dict(os.environ),
                              str(_projet(tmp_path / "a")), 300, "")
    second = demon.soumettre(commande("test_ecran.py"), dict(os.environ),
                             str(_projet(tmp_path / "b")), 300, "")

    # Les deux jobs sont admis (workers libres), mais un seul joue ses tests navigateur.
    fin, etat = time.monotonic() + 120, {}
    while time.monotonic() < fin and not etat.get("browser_position"):
        etats = [demon.etat(job["job_id"]) for job in (premier, second)]
        etat = max(etats, key=lambda e: e.get("browser_position") or 0)
        time.sleep(0.2)
    assert etat["state"] == "running" and etat["browser_position"] == 1, etat
    assert "1/1 jobs navigateur en cours" in etat["browser_slots"]
    assert "en attente d'un créneau, position 1" in ligne_avancement(etat)

    liberation.write_text("", encoding="utf-8")
    for job in (premier, second):
        final = attendre(job["job_id"], 300, au_premier_echec=False)
        assert (final["passed"], final["failed"]) == (1, 0), final
