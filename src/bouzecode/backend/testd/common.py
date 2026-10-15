# [desc] testd : dossier du démon, réglages (slots, workers, navigateurs, inactivité), appel HTTP local sans proxy, arrêt d'un arbre de process [/desc]
"""Ce que le démon et ses clients partagent.

Le proxy d'entreprise est posé dans l'environnement (HTTP_PROXY…) et urllib l'applique aussi
à 127.0.0.1 : tout appel local passe par un ouvreur SANS proxy (`ProxyHandler({})`)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_SANS_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_DEFAUTS = {"workers_total": 8, "browser_slots": 4, "browser_jobs": 2, "idle_s": 900, "collecte_s": 180}


def dossier_testd() -> Path:
    """`~/.bouzecode/testd` (ou `~/.bouzecode/testd`) ; `BZ_TESTD_HOME` le remplace (tests)."""
    surcharge = os.environ.get("BZ_TESTD_HOME")
    if surcharge:
        dossier = Path(surcharge)
    else:
        from ...paths import data_dir
        dossier = data_dir() / "testd"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def reglages() -> dict:
    """Défauts < `config.json` du dossier testd < variables `BZ_TESTD_<CLÉ>`."""
    valeurs = dict(_DEFAUTS)
    fichier = dossier_testd() / "config.json"
    if fichier.exists():
        valeurs.update(json.loads(fichier.read_text(encoding="utf-8")))
    for cle in _DEFAUTS:
        brut = os.environ.get(f"BZ_TESTD_{cle.upper()}")
        if brut:
            valeurs[cle] = int(brut)
    return valeurs


def appel_local(url: str, corps: dict | None = None, jeton: str = "",
                delai_s: float = 10.0) -> tuple[int, dict | str]:
    """GET (ou POST JSON si `corps`) sur la boucle locale, sans proxy. Rend (statut, réponse) ;
    une réponse HTTP d'erreur est rendue, pas levée. Lève OSError si personne n'écoute."""
    donnees = None if corps is None else json.dumps(corps).encode("utf-8")
    requete = urllib.request.Request(url, data=donnees, method="POST" if corps is not None else "GET")
    requete.add_header("Content-Type", "application/json")
    if jeton:
        requete.add_header("X-BZ-Token", jeton)
    try:
        with _SANS_PROXY.open(requete, timeout=delai_s) as reponse:
            return reponse.status, _decoder(reponse.read(), reponse.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as erreur:
        return erreur.code, _decoder(erreur.read(), erreur.headers.get("Content-Type", ""))


def _decoder(brut: bytes, type_contenu: str) -> dict | str:
    texte = brut.decode("utf-8", errors="replace")
    return json.loads(texte) if "json" in type_contenu and texte else texte


def tuer_arbre(pid: int) -> None:
    """Tue le process et TOUS ses descendants (workers xdist, navigateurs, serveurs)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **sans_fenetre())
        return
    import signal
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        return  # déjà mort : rien à tuer


def sans_fenetre(groupe: bool = False) -> dict:
    """Options de TOUT process lancé par testd (`subprocess.run` comme `Popen`).

    Le démon n'a pas de console : sous Windows, un enfant console lancé sans CREATE_NO_WINDOW
    reçoit une NOUVELLE console, visible — des fenêtres surgissaient sur le bureau de
    l'utilisateur le 2026-10-14. `groupe` : groupe de process à part, pour que `tuer_arbre`
    emporte toute la descendance."""
    if sys.platform != "win32":
        return {"start_new_session": True} if groupe else {}
    drapeaux = subprocess.CREATE_NO_WINDOW
    if groupe:
        drapeaux |= subprocess.CREATE_NEW_PROCESS_GROUP
    return {"creationflags": drapeaux}


def options_demon() -> tuple[str, dict]:
    """(interpréteur, options) pour lancer le démon : le `python.exe` du venv, sans fenêtre, dans
    son propre groupe de process.

    Ni `pythonw.exe` ni DETACHED_PROCESS : dans un venv uv, l'un comme l'autre n'est qu'un
    lanceur qui relance l'interpréteur de base, programme CONSOLE ; sans console à hériter,
    Windows lui en crée une, VISIBLE (fenêtre Windows Terminal vide, 2026-10-14). Avec
    CREATE_NO_WINDOW seul, le lanceur reçoit une console sans fenêtre que l'interpréteur hérite."""
    python = sys.executable
    if sys.platform != "win32":
        return python, {"start_new_session": True}
    console = Path(python).with_name("python.exe")
    if console.exists():
        python = str(console)
    return python, sans_fenetre(groupe=True)


def console_visible() -> bool:
    """Le process porte-t-il une fenêtre console (cf. `lacher_console_visible`) ?"""
    if sys.platform != "win32":
        return False
    import ctypes
    noyau = ctypes.windll.kernel32
    noyau.GetConsoleWindow.restype = ctypes.c_void_p
    return bool(noyau.GetConsoleWindow())


def lacher_console_visible() -> None:
    """Sous Windows, détache le démon d'une console qui a une fenêtre (lancement par un ancien
    client via `pythonw.exe`) : la fenêtre disparaît. Une console sans fenêtre (CREATE_NO_WINDOW)
    est gardée, ses enfants l'héritent sans rien afficher. Le stdio, devenu invalide, part dans
    devnull : le journal du démon est `daemon.log`."""
    if not console_visible():
        return
    import ctypes
    ctypes.windll.kernel32.FreeConsole()
    nul = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stderr = nul
