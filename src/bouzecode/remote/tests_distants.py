"""Jouer une suite pytest (Playwright compris) sur la VM Rundeck rec, l'agent restant local.

La commande tourne dans le depot reconstruit : `uv run <options_uv> python -m pytest <args>`, rapport
JUnit force dans le dossier resultat, captures Playwright (`--output`) rapatriees en cas d'echec.
Avec `navigateur=True`, la VM installe (ou reutilise) Chromium headless + Node compatibles glibc 2.27
avant les tests (cf. vm/navigateur/installer_navigateur.py).
"""
from bouzecode.remote.lancement import lancer_sur_rundeck

OPTIONS_UV_DEFAUT = "--extra test"
OPTIONS_PLAYWRIGHT = '--screenshot only-on-failure --output "$BZ_RESULTAT/captures/test-results"'


def commande_pytest_distante(arguments_pytest: str, options_uv: str = OPTIONS_UV_DEFAUT, navigateur: bool = True) -> str:
    options_captures = f" {OPTIONS_PLAYWRIGHT}" if navigateur else ""
    return (f'"$BZ_UV" run {options_uv} python -m pytest {arguments_pytest}{options_captures} '
            '--junitxml="$BZ_RESULTAT/junit.xml"')


def lancer_tests_sur_rundeck(projet: str, commande_pytest: str, fichiers_non_suivis: list[str] | None = None,
                             chemin: str | None = None, navigateur: bool = True,
                             options_uv: str = OPTIONS_UV_DEFAUT, version_playwright: str = "",
                             delai_s: int = 3600) -> dict:
    """`commande_pytest` : les arguments de pytest (chemins, -m, -k...). Rend le contrat de lancer_sur_rundeck."""
    execution = {
        "cible": "rundeck", "mode": "tests", "projets": [projet],
        "fichiers_non_suivis": {projet: list(fichiers_non_suivis or [])},
        "commande": commande_pytest_distante(commande_pytest, options_uv, navigateur),
        "navigateur": navigateur, "version_playwright": version_playwright, "delai_s": delai_s,
    }
    if chemin:
        execution["chemins"] = {projet: chemin}
    return lancer_sur_rundeck({"id": f"tests-{projet}"}, execution)
