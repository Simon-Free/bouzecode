# [desc] Le serveur se redemarre LUI-MEME : c'est le seul process qui a le droit de se tuer.
#
# Pourquoi ce module existe : depuis l'exterieur, tuer le serveur echoue (Stop-Process et
# taskkill rendent WinError 5 quand il a ete lance dans un contexte eleve), et `bouzeui.ps1`
# ne tue rien et lance en foreground -- il echouerait sur « port deja occupe ». Le process
# vivant, lui, a tous les droits sur lui-meme : il repond 202, lance un superviseur detache
# qui attend la liberation du port, puis se termine.
#
# Testabilite : `plan_restart` / `plan_shutdown` DELEGUENT le lancement et l'arret a deux
# callables injectables. Un test passe ses propres hooks : aucun process n'est tue, aucun
# port n'est touche, et il n'y a rien a monkeypatcher.
from __future__ import annotations

import inspect
import os
import socket
import subprocess
import sys
import threading

#  Le 202 doit avoir quitte le socket AVANT que le process meure : sans ce delai, le client
#  ne voit pas une reponse mais une connexion coupee.
DELAI_AVANT_ARRET = 0.4
#  Le superviseur attend la liberation du port (le serveur met un instant a lacher le socket).
ATTENTE_PORT_MAX = 60.0
MODULE_SERVEUR = "bouzecode.web_v2"

#  Superviseur lance dans un process DETACHE : il survit a la mort de son parent (c'est tout
#  l'interet), attend que le port soit libre, puis relance le serveur avec la meme commande.
_SUPERVISEUR = (
    "import socket, subprocess, sys, time\n"
    "port = int(sys.argv[1]); cwd = sys.argv[2]; commande = sys.argv[3:]\n"
    "fin = time.time() + %f\n"
    "while time.time() < fin:\n"
    "    s = socket.socket()\n"
    "    libre = s.connect_ex(('127.0.0.1', port)) != 0\n"
    "    s.close()\n"
    "    if libre:\n"
    "        break\n"
    "    time.sleep(0.2)\n"
    "subprocess.Popen(commande, cwd=cwd)\n"
) % ATTENTE_PORT_MAX

_hooks: dict = {"spawn": None, "quit": None}


def set_hooks(spawn=None, quit=None) -> None:
    """Remplace le lanceur et/ou l'arret (tests : on n'y met pas de vrai process)."""
    if spawn is not None:
        _hooks["spawn"] = spawn
    if quit is not None:
        _hooks["quit"] = quit


def reset_hooks() -> None:
    _hooks["spawn"] = None
    _hooks["quit"] = None


def commande_de_relance(port: int, python: str = "") -> list[str]:
    """La commande EXACTE du serveur : le meme interpreteur que le process courant."""
    return [python or sys.executable, "-m", MODULE_SERVEUR, "--port", str(int(port))]


def port_libre(port: int) -> bool:
    connexion = socket.socket()
    try:
        return connexion.connect_ex(("127.0.0.1", int(port))) != 0
    finally:
        connexion.close()


def _appeler(hook, args: tuple):
    """Appelle `hook` avec autant d'arguments qu'il en accepte.

    Un hook de test s'ecrit souvent `lambda: journal.append("spawn")` : lui imposer
    la signature complete transformerait un test lisible en TypeError."""
    try:
        parametres = inspect.signature(hook).parameters
    except (TypeError, ValueError):
        return hook(*args)
    accepte_tout = any(p.kind == p.VAR_POSITIONAL for p in parametres.values())
    if accepte_tout:
        return hook(*args)
    positionnels = [p for p in parametres.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return hook(*args[:len(positionnels)])


def _spawn_detache(commande: list[str], cwd: str) -> None:
    drapeaux = 0
    for nom in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        drapeaux |= getattr(subprocess, nom, 0)
    port = commande[commande.index("--port") + 1]
    subprocess.Popen(
        [commande[0], "-c", _SUPERVISEUR, port, cwd, *commande],
        cwd=cwd,
        creationflags=drapeaux,
        close_fds=True,
    )


def _quitter_differe() -> None:
    #  os._exit : pas de teardown Flask, pas de thread qui retient le process.
    threading.Timer(DELAI_AVANT_ARRET, lambda: os._exit(0)).start()


def plan_restart(port: int, python: str = "", spawn=None, quit=None,
                 cwd: str = "") -> dict:
    """Prepare la relance, la lance, PUIS demande l'arret. Rend ce qu'on repond au client."""
    commande = commande_de_relance(port, python)
    lanceur = spawn or _hooks["spawn"] or _spawn_detache
    arret = quit or _hooks["quit"] or _quitter_differe
    #  Ordre impose : le successeur est arme AVANT qu'on se tue, sinon un echec de
    #  lancement laisserait l'utilisateur sans serveur du tout.
    _appeler(lanceur, (commande, cwd or os.getcwd()))
    _appeler(arret, ())
    return {"pid": os.getpid(), "port": int(port), "commande": commande}


def plan_shutdown(quit=None) -> dict:
    """Arret pur : aucun successeur n'est lance."""
    arret = quit or _hooks["quit"] or _quitter_differe
    _appeler(arret, ())
    return {"pid": os.getpid()}
