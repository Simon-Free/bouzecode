# [desc] testd, intégration réelle : sous le démon, une action Playwright sur un élément absent échoue en 5 s (pas 30 s) ; un `set_default_timeout` posé par le test reste maître ; sauté sans Playwright installé [/desc]
from __future__ import annotations

import os
from pathlib import Path

import pytest

from bouzecode.backend.testd.rendu import attendre, texte_etat
from bouzecode.backend.tools.ops.shell_env import strip_inherited_python_home
from tests.backend.testd.aides import projet

_PYTHON_PW = Path(r"C:\Users\user01\PycharmProjects\demo\demo_application\.venv\Scripts\python.exe")

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(not _PYTHON_PW.exists(), reason="pas de venv avec Playwright sur ce poste"),
]

#  Edge du poste, sans proxy : comme le plugin `_bz_pw_patch` le fait pour un vrai lancement.
_FICHIERS = {
    "test_delais.py": """
        import time
        from playwright.sync_api import sync_playwright, TimeoutError as DelaiDepasse

        def _clic_sur_absent(regler):
            with sync_playwright() as p:
                navigateur = p.chromium.launch(channel="msedge", args=["--no-proxy-server"])
                contexte = navigateur.new_context()
                regler(contexte)
                page = contexte.new_page()
                page.set_content("<p>rien</p>")
                debut = time.monotonic()
                try:
                    page.click("#absent")
                except DelaiDepasse as erreur:
                    message = str(erreur)
                navigateur.close()
                return time.monotonic() - debut, message

        def test_delai_par_defaut_de_testd():
            duree, message = _clic_sur_absent(lambda contexte: None)
            assert "5000ms" in message and duree < 10, (duree, message)

        def test_delai_explicite_du_test_garde():
            duree, message = _clic_sur_absent(lambda contexte: contexte.set_default_timeout(1500))
            assert "1500ms" in message and duree < 5, (duree, message)
    """,
}


def test_une_action_sur_un_element_absent_echoue_en_5_s(demon, tmp_path):
    """Le délai par défaut des actions est 5 s sous le démon ; le délai fixé par le test garde
    sa valeur."""
    racine = projet(tmp_path / "p", _FICHIERS)
    env = strip_inherited_python_home(dict(os.environ))
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    cmd = [str(_PYTHON_PW), "-m", "pytest", "-v", "-p", "no:cacheprovider", "test_delais.py"]
    job = demon.soumettre(cmd, env, str(racine), 300, str(_PYTHON_PW))
    final = attendre(job["job_id"], 180, au_premier_echec=False)
    assert final["passed"] == 2 and final["failed"] == 0, texte_etat(final)
