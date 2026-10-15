# [desc] testd : la collecte sépare les tests navigateur (marqueur, fixture page/browser/context) des autres ; un sous-run ne joue que son groupe et journalise échecs et test en cours [/desc]
from __future__ import annotations

import os
import subprocess

from bouzecode.backend.testd.run.split import (
    avec_workers, collecter, env_sous_run, lire_evenements, sans_xdist, workers_demandes,
)
from bouzecode.backend.testd.common import sans_fenetre
from tests.backend.testd.aides import commande, projet

_FICHIERS = {
    "conftest.py": """
        import pytest
        from playwright.sync_api import Page
        def pytest_configure(config):
            config.addinivalue_line("markers", "browser: test navigateur")
            config.addinivalue_line("markers", "maison: marqueur du projet")
        @pytest.fixture
        def page():
            return "une page de navigateur (fixture d'un module qui importe Playwright)"
    """,
    "test_html.py": """
        import pytest
        @pytest.fixture
        def page():
            return "<html>rendu par TestClient, pas de navigateur</html>"
        def test_page_html(page):
            assert page
    """,
    "test_direct.py": """
        from playwright.sync_api import sync_playwright
        def test_lance_son_navigateur():
            assert sync_playwright
    """,
    "test_mixte.py": """
        import pytest
        def test_calcul():
            assert 1 + 1 == 2
        def test_casse():
            assert 1 + 1 == 3, "addition fausse"
        def test_avec_page(page):
            assert page
        @pytest.mark.browser
        def test_marque():
            assert True
        @pytest.mark.maison
        def test_marqueur_maison():
            assert True
    """,
}


def test_collecte_classe_par_marqueur_et_par_fixture(tmp_path):
    racine = projet(tmp_path / "p", _FICHIERS)
    cmd = commande("test_mixte.py", "test_direct.py", "test_html.py", workers=2)
    groupes, note = collecter(cmd, dict(os.environ), str(racine), tmp_path, "browser,e2e,maison")
    assert note == "" and groupes["deselected"] == {}
    noms = {cle: sorted(n.split("::")[1] for n in groupes[cle]) for cle in ("browser", "other")}
    assert noms == {"browser": ["test_avec_page", "test_lance_son_navigateur", "test_marque",
                                "test_marqueur_maison"],
                    "other": ["test_calcul", "test_casse", "test_page_html"]}


def test_sous_run_ne_joue_que_son_groupe_et_journalise_les_echecs(tmp_path):
    racine = projet(tmp_path / "p", _FICHIERS)
    evenements = tmp_path / "ev"
    evenements.mkdir()
    env = env_sous_run(dict(os.environ), evenements, "other", "browser,e2e,maison")
    sortie = subprocess.run(commande("test_mixte.py", workers=2) + ["-p", "_bz_testd_plugin"],
                            cwd=racine, env=env, capture_output=True, text=True, timeout=120,
                            **sans_fenetre())
    assert "1 passed" in sortie.stdout and "1 failed" in sortie.stdout, sortie.stdout
    avancement = lire_evenements([evenements])
    assert (avancement["done"], avancement["passed"], avancement["failed"]) == (2, 1, 1)
    assert avancement["failures"][0]["id"].endswith("test_casse")
    assert "addition fausse" in avancement["failures"][0]["excerpt"]
    assert avancement["longest"] is None


def test_options_xdist_retirees_et_reposees():
    cmd = ["py", "-m", "pytest", "-n", "4", "-v", "--dist", "loadfile", "t.py"]
    assert sans_xdist(cmd) == ["py", "-m", "pytest", "-v", "t.py"]
    assert workers_demandes(cmd) == 4 and workers_demandes(["py", "-n2"]) == 2
    assert avec_workers(cmd, 2)[-2:] == ["-n", "2"]
    assert "-n" not in avec_workers(cmd, 1)


_AIDES = {
    "aide_harnais.py": """
        from playwright.sync_api import Page, sync_playwright
        def session():
            return sync_playwright
    """,
    "aide_types.py": """
        from playwright.sync_api import Page
        def annoter(page: Page):
            return page
    """,
    "test_exo.py": """
        from aide_harnais import session
        def test_parcours_de_l_exercice():
            assert session
    """,
    "test_typage.py": """
        from aide_types import annoter
        def test_annotation_seulement():
            assert annoter
    """,
}


def test_aide_qui_lance_un_navigateur_classe_le_fichier_navigateur(tmp_path):
    """Session B4 : `tests/test_exercise_*.py` importaient un harnais maison qui lance Chromium ;
    une aide qui n'importe que `Page` pour une annotation ne compte pas."""
    racine = projet(tmp_path / "p", _AIDES)
    groupes, note = collecter(commande("test_exo.py", "test_typage.py"), dict(os.environ),
                              str(racine), tmp_path, "browser,e2e")
    assert note == ""
    assert groupes["browser"] == ["test_exo.py::test_parcours_de_l_exercice"]
    assert groupes["other"] == ["test_typage.py::test_annotation_seulement"]
