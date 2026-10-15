# [desc] testd : aucun process lancé par le démon n'ouvre de fenêtre console (CREATE_NO_WINDOW partout, démon par python.exe sans fenêtre, vrai démon sans console visible) [/desc]
"""Le 2026-10-14, des consoles surgissaient sur le bureau : le démon n'a pas de console, et
Windows en donne une NOUVELLE, visible, à chaque enfant console lancé sans CREATE_NO_WINDOW."""
from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

import bouzecode.backend.testd as testd
from bouzecode.backend.testd.common import options_demon, sans_fenetre

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="drapeaux Windows")


def test_l_aide_pose_create_no_window():
    assert sans_fenetre()["creationflags"] & subprocess.CREATE_NO_WINDOW
    groupe = sans_fenetre(groupe=True)["creationflags"]
    assert groupe & subprocess.CREATE_NO_WINDOW and groupe & subprocess.CREATE_NEW_PROCESS_GROUP
    python, options = options_demon()
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    # DETACHED_PROCESS ou pythonw.exe : l'interpréteur de base relancé par le lanceur du venv
    # n'a plus de console à hériter et Windows lui en ouvre une visible.
    assert not options["creationflags"] & subprocess.DETACHED_PROCESS
    assert Path(python).name == "python.exe"


def _fenetres_python_visibles() -> set[tuple[int, str]]:
    """Fenêtres de premier niveau visibles dont le titre nomme python (la console surgie
    s'intitulait `…/Scripts/pythonw.exe`, dans Windows Terminal : son pid n'est pas le nôtre)."""
    import ctypes
    from ctypes import wintypes
    utilisateur = ctypes.windll.user32
    trouvees = set()

    def visiter(fenetre, _):
        if utilisateur.IsWindowVisible(fenetre):
            tampon = ctypes.create_unicode_buffer(512)
            utilisateur.GetWindowTextW(fenetre, tampon, 512)
            if "python" in tampon.value.lower():
                trouvees.add((fenetre, tampon.value))
        return True

    rappel = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visiter)
    utilisateur.EnumWindows(rappel, 0)
    return trouvees


def test_le_vrai_demon_ne_montre_aucune_console(demon):
    avant = _fenetres_python_visibles()
    info = demon.assurer_demon()
    from bouzecode.backend.testd.common import appel_local
    statut, sante = appel_local(f"http://127.0.0.1:{info['port']}/health")
    assert statut == 200 and sante["console_visible"] is False
    time.sleep(1.0)  # une console surgie met un instant à s'afficher
    assert _fenetres_python_visibles() - avant == set()


def _appels_de_process(source: str):
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute) \
                and noeud.func.attr in ("run", "Popen") and getattr(noeud.func.value, "id", "") == "subprocess":
            yield noeud


def test_chaque_lancement_de_testd_passe_par_l_aide():
    oublis = []
    for fichier in Path(testd.__file__).parent.rglob("*.py"):
        for appel in _appels_de_process(fichier.read_text(encoding="utf-8")):
            etendus = [k.value for k in appel.keywords if k.arg is None]
            noms = {getattr(getattr(e, "func", None), "id", "") or getattr(e, "id", "") for e in etendus}
            if not noms & {"sans_fenetre", "options"}:
                oublis.append(f"{fichier.name}:{appel.lineno}")
    assert oublis == []
