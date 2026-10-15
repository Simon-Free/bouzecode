# [desc] testd : un test bloqué au-delà de SA limite (tests.yaml) fait tuer son sous-run bien avant le délai du job ; le rapport dit quel test, depuis combien de temps, et où il attend (pile faulthandler) ; un test lent (`impacted.slow`, marqueur `slow`) n'est pas tué à la limite courte [/desc]
"""Job 85b72fb9 (B4, 2026-10-14) : un test en interblocage a tenu 295 s, tout le délai du job."""
from __future__ import annotations

import os
import time

from bouzecode.backend.testd.rendu import attendre, texte_etat
from tests.backend.testd.aides import commande, projet

_BLOQUE = {
    "test_bloque.py": """
        import threading
        def test_rapide():
            assert True
        def test_attend_un_verrou_jamais_rendu():
            verrou = threading.Lock()
            verrou.acquire()
            verrou.acquire()
    """,
}

#  Limite courte de 1 s (tué à 1 + 5 s de marge) : les tests lents durent 8 s, au-delà.
_LENTS = {
    "conftest.py": """
        def pytest_configure(config):
            config.addinivalue_line("markers", "slow: test long connu")
    """,
    "test_lent_liste.py": """
        import time
        def test_liste_lent_dans_tests_yaml():
            time.sleep(8)
    """,
    "test_lent_marque.py": """
        import time, pytest
        @pytest.mark.slow
        def test_marque_slow():
            time.sleep(8)
    """,
    "test_court.py": """
        import threading
        def test_court_bloque():
            verrou = threading.Lock()
            verrou.acquire()
            verrou.acquire()
    """,
}


def _tests_yaml(racine, contenu: str) -> None:
    (racine / ".bouzecode").mkdir()
    (racine / ".bouzecode" / "tests.yaml").write_text(contenu, encoding="utf-8")


def test_test_bloque_tue_son_sous_run_et_montre_sa_pile(demon, tmp_path):
    """Un test hors navigateur bloqué est tué à la limite courte, même si celle des tests
    navigateur est longue ; le rapport le nomme et montre où il attend."""
    racine = projet(tmp_path / "p", _BLOQUE)
    _tests_yaml(racine, "timeouts:\n  per_test: 3\n  per_test_browser: 600\n")
    debut = time.monotonic()
    job = demon.soumettre(commande("test_bloque.py"), dict(os.environ), str(racine), 300, "")
    final = attendre(job["job_id"], 120, au_premier_echec=False)
    assert time.monotonic() - debut < 60, final
    assert final["state"] == "done" and not final["timed_out"], final
    assert final["passed"] == 1, final
    rapport = texte_etat(final)
    assert "test_bloque.py::test_attend_un_verrou_jamais_rendu bloqué depuis" in rapport, rapport
    assert "limite 3 s" in rapport and "`timeouts.per_test`" in rapport
    assert "Pile du test (faulthandler)" in rapport and "test_bloque.py" in rapport.split("Pile du test")[1]


def test_test_lent_survit_a_la_limite_courte(demon, tmp_path):
    """Les tests lents (listés sous `impacted.slow` ou marqués `slow`) dépassent la limite
    courte sans être tués ; un test court bloqué dans le même run l'est, lui."""
    racine = projet(tmp_path / "p", _LENTS)
    _tests_yaml(racine, "timeouts:\n  per_test: 1\n"
                        "impacted:\n  slow: ['test_lent_liste.py']\n")
    #  Fichiers dans l'ordre donné : les lents d'abord, le bloqué ensuite tue le sous-run.
    cibles = commande("test_lent_liste.py", "test_lent_marque.py", "test_court.py")
    job = demon.soumettre(cibles, dict(os.environ), str(racine), 300, "")
    final = attendre(job["job_id"], 120, au_premier_echec=False)
    assert final["state"] == "done" and not final["timed_out"], final
    assert final["passed"] == 2, texte_etat(final)
    rapport = texte_etat(final)
    tues = [ligne for ligne in rapport.splitlines() if "bloqué depuis" in ligne]
    assert len(tues) == 1 and "test_court.py::test_court_bloque" in tues[0], rapport
