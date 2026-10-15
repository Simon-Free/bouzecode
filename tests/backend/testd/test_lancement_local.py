# [desc] testd, intégration réelle : un vrai lancement Chromium par le plugin prend la coquille headless livrée (Edge système si elle manque, et c'est dit), est tué à sa fermeture sans laisser de process ; le navigateur chaud choisit pareil [/desc]
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.testd.common import sans_fenetre, tuer_arbre
from bouzecode.backend.testd.run.split import DOSSIER_PLUGIN
from bouzecode.backend.testd.warm.browser_pool import NavigateursChauds
from tests.backend.testd.aides import projet

_PYTHON_PW = Path(r"C:\Users\user01\PycharmProjects\demo\demo_application\.venv\Scripts\python.exe")

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(not _PYTHON_PW.exists(), reason="pas de venv avec Playwright sur ce poste"),
]

_TEST_LOCAL = {
    "test_local.py": """
        import json, time
        from playwright.sync_api import sync_playwright
        def test_lancement_puis_fermeture():
            with sync_playwright() as p:
                navigateur = p.chromium.launch()
                page = navigateur.new_context().new_page()
                page.set_content("<p>ok</p>")
                agent = page.evaluate("navigator.userAgent")
                infos = navigateur.new_browser_cdp_session().send("SystemInfo.getProcessInfo")
                debut = time.monotonic()
                navigateur.close()
                json.dump({"agent": agent, "pids": [i["id"] for i in infos["processInfo"]],
                           "fermeture_s": time.monotonic() - debut}, open("lancement.json", "w"))
    """,
}


def _env_du_projet(tmp_path: Path, **en_plus: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME",
                                                            "BZ_PW_WS", "BZ_PW_CDP", "BZ_PW_DEMANDE")}
    return {**env, "PYTHONPATH": DOSSIER_PLUGIN, "BZ_PW_NOTES": str(tmp_path / "notes.txt"), **en_plus}


def _lancer_sans_demon(tmp_path: Path, **en_plus: str) -> dict:
    """Le test du projet lance Chromium lui-même, sans navigateur chaud : vrai lancement du patch."""
    racine = projet(tmp_path / "p", _TEST_LOCAL)
    journal = tmp_path / "pytest_imbrique.txt"
    with open(journal, "w", encoding="utf-8") as flux:
        proc = subprocess.Popen([str(_PYTHON_PW), "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider",
                                 "-p", "_bz_pw_patch", "test_local.py"], cwd=racine,
                                env=_env_du_projet(tmp_path, **en_plus), stdout=flux,
                                stderr=subprocess.STDOUT, **sans_fenetre(groupe=True))
    try:
        proc.wait(timeout=90)
    finally:
        tuer_arbre(proc.pid)
    assert proc.returncode == 0, journal.read_text(encoding="utf-8")[-3000:]
    return json.loads((racine / "lancement.json").read_text())


def _vivants(pids: list[int]) -> list[int]:
    liste = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                           timeout=60, **sans_fenetre()).stdout
    presents = {int(l.split('","')[1]) for l in liste.splitlines() if l.count('","') >= 2}
    return sorted(set(pids) & presents)


def _notes(tmp_path: Path) -> str:
    fichier = tmp_path / "notes.txt"
    return fichier.read_text(encoding="utf-8") if fichier.exists() else ""


def test_lancement_local_prend_la_coquille_livree_et_la_tue_a_la_fermeture(tmp_path):
    """Sans navigateur chaud, le test tourne sur la coquille headless de Playwright (pas Edge), et
    sa fermeture tue le navigateur : aucun process ne reste, la fermeture ne traîne pas."""
    lancement = _lancer_sans_demon(tmp_path)
    assert "HeadlessChrome/" in lancement["agent"] and "Edg/" not in lancement["agent"], lancement
    assert "msedge" not in _notes(tmp_path)
    assert _vivants(lancement["pids"]) == []
    assert lancement["fermeture_s"] < 5.0, lancement


def test_coquille_absente_edge_systeme_et_c_est_dit(tmp_path):
    """Coquille de cette version de Playwright non installée : le patch choisit Edge système, et la
    note du job le dit. Le choix seul est vérifié dans le python du projet : lancer Edge pour de
    vrai pend par moments (90 s et plus, mesuré ici même), c'est la raison du changement."""
    vide = tmp_path / "aucun_navigateur"
    vide.mkdir()
    code = "import _bz_pw_lancement as l, sys; print(l.canal_par_defaut(lambda t: print(t, file=sys.stderr)))"
    sortie = subprocess.run([str(_PYTHON_PW), "-c", code], capture_output=True, text=True, timeout=60,
                            env=_env_du_projet(tmp_path, PLAYWRIGHT_BROWSERS_PATH=str(vide)), **sans_fenetre())
    assert sortie.stdout.strip() == "msedge", sortie
    assert "chromium_headless_shell-1208 absente" in sortie.stderr and "msedge" in sortie.stderr

    sortie = subprocess.run([str(_PYTHON_PW), "-c", code], capture_output=True, text=True, timeout=60,
                            env=_env_du_projet(tmp_path), **sans_fenetre())
    assert (sortie.stdout.strip(), sortie.stderr) == ("None", ""), sortie


def test_navigateur_chaud_choisit_la_coquille_si_elle_est_installee(tmp_path, monkeypatch):
    """Le démon sonde le python du projet : coquille installée -> elle d'abord ; absente -> Edge
    d'abord, et la note du job le dit."""
    monkeypatch.delenv("BZ_TESTD_BROWSER_CHANNEL", raising=False)
    env = _env_du_projet(tmp_path)
    sonde = NavigateursChauds(tmp_path).sonde(str(_PYTHON_PW), env)
    assert sonde["coquille"] and sonde["coquille"] == sonde["attendue"], sonde
    assert NavigateursChauds.canaux(sonde) == (["", "msedge"], "")

    vide = tmp_path / "aucun_navigateur"
    vide.mkdir()
    sonde = NavigateursChauds(tmp_path).sonde(str(_PYTHON_PW), {**env, "PLAYWRIGHT_BROWSERS_PATH": str(vide)})
    canaux, note = NavigateursChauds.canaux(sonde)
    assert sonde["coquille"] == "" and canaux == ["msedge", ""]
    assert f"chromium_headless_shell-{sonde['attendue']} absente" in note
