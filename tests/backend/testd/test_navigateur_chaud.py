# [desc] testd, intégration réelle : les tests navigateur d'un job se branchent sur le navigateur chaud partagé (launch-server), relancé s'il meurt ; sauté sans Playwright installé [/desc]
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.testd.common import sans_fenetre
from bouzecode.backend.testd.rendu import attendre
from bouzecode.backend.tools.ops.shell_env import strip_inherited_python_home
from bouzecode.backend.tools.ops.test_runner import _inject_playwright_plugin
from tests.backend.testd.aides import projet

_PYTHON_PW = Path(r"C:\Users\user01\PycharmProjects\demo\demo_application\.venv\Scripts\python.exe")

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(not _PYTHON_PW.exists(), reason="pas de venv avec Playwright sur ce poste"),
]

_FICHIERS = {
    "test_simple.py": "def test_hors_navigateur():\n    assert True\n",
    "test_nav.py": """
        import os, pytest
        from playwright.sync_api import sync_playwright
        def test_page_rendue():
            with sync_playwright() as p:
                navigateur = p.chromium.launch()
                assert navigateur.is_connected()
                page = navigateur.new_context().new_page()
                page.set_content("<h1>chaud</h1>")
                assert page.inner_text("h1") == "chaud"
                open("connecte.txt", "w").write(os.environ.get("BZ_PW_WS", ""))
                navigateur.close()
    """,
}


def _env_du_projet() -> dict:
    """Env d'un autre venv (python 3.13) : sans le PYTHONHOME ni le PYTHONPATH de ce run."""
    env = strip_inherited_python_home(dict(os.environ))
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    return env


def _job(demon, racine):
    env = _env_du_projet()
    cmd = [str(_PYTHON_PW), "-m", "pytest", "-v", "-p", "no:cacheprovider", "test_simple.py", "test_nav.py"]
    plugin = _inject_playwright_plugin(env, cmd)
    job = demon.soumettre(cmd, env, str(racine), 300, str(_PYTHON_PW))
    etat = attendre(job["job_id"], 300, au_premier_echec=False)
    shutil.rmtree(plugin, ignore_errors=True)
    return etat


def test_navigateur_chaud_partage_et_relance(demon, tmp_path):
    racine = projet(tmp_path / "p", _FICHIERS)
    etat = _job(demon, racine)
    assert (etat["passed"], etat["failed"]) == (2, 0), etat
    assert [p["label"] for p in etat["parts"]] == ["other", "browser"]
    ws = (racine / "connecte.txt").read_text()
    assert ws.startswith("ws://127.0.0.1:") and "unreachable" not in etat["notes"]

    # Le navigateur chaud meurt : le job suivant le relance et passe quand même.
    _tuer_serveur_playwright(ws)
    etat = _job(demon, racine)
    assert (etat["passed"], etat["failed"]) == (2, 0), etat
    assert "relancé" in etat["notes"]
    assert (racine / "connecte.txt").read_text() != ws


def _tuer_serveur_playwright(ws: str) -> None:
    """Tue le process qui écoute sur le port du navigateur chaud (et sa descendance)."""
    port = ws.split(":")[2].split("/")[0]
    sortie = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", **sans_fenetre()).stdout
    pids = {l.split()[-1] for l in sortie.splitlines() if f"127.0.0.1:{port} " in l and "LISTENING" in l}
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, **sans_fenetre())


_TUE_EN_VOL = {
    "test_vol.py": """
        import os, pathlib, subprocess, pytest
        from playwright.sync_api import sync_playwright
        @pytest.mark.browser
        def test_navigateur_tue_en_plein_test():
            with sync_playwright() as p:
                navigateur = p.chromium.launch()
                marque = pathlib.Path("deja_tue.txt")
                if not marque.exists():
                    marque.write_text("1")
                    port = os.environ["BZ_PW_WS"].split(":")[2].split("/")[0]
                    netstat = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=0x08000000).stdout
                    for ligne in netstat.splitlines():
                        if f"127.0.0.1:{port} " in ligne and "LISTENING" in ligne:
                            subprocess.run(["taskkill", "/F", "/T", "/PID", ligne.split()[-1]], capture_output=True, creationflags=0x08000000)
                page = navigateur.new_context().new_page()
                page.set_content("<p>ok</p>")
    """,
}


def test_tests_navigateur_rejoues_si_le_navigateur_meurt_en_vol(demon, tmp_path):
    racine = projet(tmp_path / "p", _TUE_EN_VOL)
    env = _env_du_projet()
    cmd = [str(_PYTHON_PW), "-m", "pytest", "-v", "-p", "no:cacheprovider", "test_vol.py"]
    plugin = _inject_playwright_plugin(env, cmd)
    job = demon.soumettre(cmd, env, str(racine), 300, str(_PYTHON_PW))
    etat = attendre(job["job_id"], 300, au_premier_echec=False)
    shutil.rmtree(plugin, ignore_errors=True)
    assert "rejoués une fois" in etat["notes"], etat
    assert (etat["passed"], etat["failed"]) == (1, 0), etat


_HARNAIS_CACHE = {
    "test_harnais.py": """
        import importlib, time
        def _lanceur():  # invisible au classement : rien de Playwright dans le module
            return importlib.import_module("playwright.sync_api").sync_playwright
        def test_parcours_par_un_harnais():
            with _lanceur()() as p:
                navigateur = p.chromium.launch(headless=True, channel="chrome", args=["--mute-audio"])
                page = navigateur.new_context().new_page()
                page.set_content("<p>ok</p>")
                debut = time.monotonic()
                navigateur.close()
                open("fermeture.txt", "w").write(f"{time.monotonic() - debut:.3f}")
    """,
}


def test_navigateur_chaud_servi_a_la_demande_et_classement_appris(demon, tmp_path):
    """Session B4 : un harnais lançait Chromium hors de toute fixture ; classé « hors navigateur »,
    chaque test démarrait et fermait (8 à 90 s) son navigateur. Le navigateur chaud est servi à
    la première demande, la fermeture n'est qu'une déconnexion, et le fichier est appris
    « navigateur » pour les jobs suivants."""
    racine = projet(tmp_path / "p", _HARNAIS_CACHE)
    env = _env_du_projet()
    cmd = [str(_PYTHON_PW), "-m", "pytest", "-v", "-p", "no:cacheprovider", "test_harnais.py"]
    plugin = _inject_playwright_plugin(env, cmd)
    job = demon.soumettre(cmd, env, str(racine), 300, str(_PYTHON_PW))
    etat = attendre(job["job_id"], 300, au_premier_echec=False)
    shutil.rmtree(plugin, ignore_errors=True)
    assert (etat["passed"], etat["failed"]) == (1, 0), etat
    assert "real launch" not in etat["notes"], etat["notes"]
    assert float((racine / "fermeture.txt").read_text()) < 1.0
    classes = next((tmp_path / "test_durations" / "fichiers").glob("*.json")).read_text(encoding="utf-8")
    assert '"test_harnais.py": {"browser": true' in classes, classes
