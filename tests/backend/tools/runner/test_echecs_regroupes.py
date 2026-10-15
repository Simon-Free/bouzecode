# [desc] RunPythonTest regroupe les échecs de même signature (type + 1re ligne normalisée) et donne un remède d'une ligne pour les signatures d'environnement connues ; vrai mini projet. [/desc]
"""Suite finale du 2026-10-13 : 98 failed + 149 errors, dont 144 fois la même erreur
d'environnement (`BrowserType.launch: Executable doesn't exist at …chromium_headless_shell-1208…`)
et ~80 timeouts navigateur. Seuls ~5 échecs venaient du changement. Le rapport montrait les
échecs un par un : l'agent n'y voyait pas les 5 vrais, et en a « corrigé » un en affaiblissant
un test de sécurité. Ici, le vrai outil sur un vrai mini projet qui reproduit ces signatures.
"""
from __future__ import annotations

import textwrap

import pytest

from bouzecode.backend.tools.ops.test_runner import run_python_test

_PROJET = {
    "pyproject.toml": '[project]\nname = "demo"\nversion = "0"\n',
    "pwerrors.py": "class Error(Exception):\n    pass\n",
    "test_env.py": textwrap.dedent('''\
        import time
        import pytest
        import pwerrors

        REV = "C:\\\\Users\\\\u{n}\\\\AppData\\\\Local\\\\ms-playwright\\\\chromium_headless_shell-1208\\\\chrome-win\\\\headless_shell.exe"

        @pytest.mark.parametrize("n", range(6))
        def test_browser(n):
            raise pwerrors.Error("BrowserType.launch: Executable doesn't exist at " + REV.format(n=n))

        @pytest.mark.parametrize("n", range(3))
        def test_import(n):
            import absent_xyz_module  # noqa: F401

        @pytest.mark.parametrize("port", [8101, 8102])
        def test_serveur(port):
            raise ConnectionRefusedError(10061, f"connexion refusée sur le port {port}")

        def test_port_pris():
            raise OSError(98, "Address already in use")

        def test_vrai_echec():
            assert 1 == 2

        @pytest.fixture
        def lent():
            time.sleep(2.0)

        @pytest.mark.parametrize("n", range(3))
        def test_setup_lent(lent, n):
            pass
    '''),
}


@pytest.fixture(scope="module")
def resultat(tmp_path_factory):
    racine = tmp_path_factory.mktemp("regroupes")
    for nom, contenu in _PROJET.items():
        (racine / nom).write_text(contenu, encoding="utf-8")
    #  Un seul run pour tout le module : son HOME (où la sortie complète est sauvée) est le
    #  sien, pas le HOME partagé du worker.
    with pytest.MonkeyPatch.context() as env:
        for variable in ("HOME", "USERPROFILE"):
            env.setenv(variable, str(tmp_path_factory.mktemp("home")))
        return run_python_test(targets=[str(racine / "test_env.py")], parallel="4", timeout=120)


def test_meme_signature_groupee_une_ligne_avec_exemple(resultat):
    assert "6 × pwerrors Error: BrowserType.launch: Executable doesn't exist at <path> " \
           "(e.g. test_env.py::test_browser[" in resultat, resultat


def test_un_seul_extrait_par_signature(resultat):
    assert resultat.count("____ test_browser[") == 1, resultat


def test_remede_navigateur_playwright_exige_l_accord_et_propose_msedge(resultat):
    ligne = next(l for l in resultat.splitlines() if "chromium_headless_shell-1208" in l)
    assert ".exe" in ligne and "accord" in ligne and 'channel="msedge"' in ligne


def test_signatures_d_environnement_connues(resultat):
    assert "3 × ModuleNotFoundError: No module named 'absent_xyz_module'" in resultat
    assert "2 × ConnectionRefusedError: [Errno N] connexion refusée sur le port N" in resultat
    bas = resultat.lower()
    assert "connexion refusée" in bas and "serveur" in bas
    assert "port déjà pris" in bas
    assert "module absent_xyz_module absent" in bas


def test_setups_a_deux_secondes_signales_comme_connexion_refusee(resultat):
    assert "setups à ~2 s" in resultat, resultat


def test_erreur_inconnue_rendue_telle_quelle(resultat):
    assert "assert 1 == 2" in resultat
