# [desc] testd : côté agent — démarre le démon à la demande, soumet un job, lit son état, l'annule [/desc]
"""Le démon est démarré par le premier agent qui en a besoin, puis partagé par tous. Un verrou
fichier (création exclusive) évite que deux agents en lancent chacun un."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .common import appel_local, dossier_testd, options_demon, sans_fenetre

_DELAI_DEMARRAGE_S = 20
_RACINE_SRC = str(Path(__file__).resolve().parents[3])  # .../src, d'où `bouzecode` s'importe


class DemonIndisponible(RuntimeError):
    pass


def demon_actif() -> bool:
    """`BZ_TESTD=0` coupe le démon, `=1` le force. Par défaut il sert, sauf dans un process de
    test (PYTEST_CURRENT_TEST) : les tests de RunPythonTest exercent l'exécution directe."""
    choix = os.environ.get("BZ_TESTD", "")
    if choix in ("0", "1"):
        return choix == "1"
    return "PYTEST_CURRENT_TEST" not in os.environ


def _lire_info() -> dict | None:
    fichier = dossier_testd() / "daemon.json"
    if not fichier.exists():
        return None
    info = json.loads(fichier.read_text(encoding="utf-8"))
    try:
        statut, _ = appel_local(f"http://127.0.0.1:{info['port']}/health", delai_s=3)
    except OSError:
        return None
    return info if statut == 200 else None


def _lancer_demon() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = _RACINE_SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("PYTEST_CURRENT_TEST", None)
    python, _ = options_demon()
    subprocess.run([python, "-m", "bouzecode.backend.testd.daemon", "--detach"], env=env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=60, **sans_fenetre())


def assurer_demon() -> dict:
    """{pid, port, token} du démon, démarré au besoin. Lève DemonIndisponible."""
    info = _lire_info()
    if info:
        return info
    verrou = dossier_testd() / "start.lock"
    if verrou.exists() and time.time() - verrou.stat().st_mtime > 2 * _DELAI_DEMARRAGE_S:
        verrou.unlink(missing_ok=True)  # verrou abandonné par un démarrage mort
    try:
        descripteur = os.open(verrou, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descripteur)
        j_ai_le_verrou = True
    except FileExistsError:
        j_ai_le_verrou = False  # un autre agent démarre le démon : on l'attend
    try:
        if j_ai_le_verrou:
            _lancer_demon()
        fin = time.monotonic() + _DELAI_DEMARRAGE_S
        while time.monotonic() < fin:
            info = _lire_info()
            if info:
                return info
            time.sleep(0.2)
    finally:
        if j_ai_le_verrou:
            verrou.unlink(missing_ok=True)
    raise DemonIndisponible(f"démon de tests muet après {_DELAI_DEMARRAGE_S} s "
                            f"(journal : {dossier_testd() / 'daemon.log'})")


def _appel(chemin: str, corps: dict | None = None) -> dict:
    info = assurer_demon()
    statut, reponse = appel_local(f"http://127.0.0.1:{info['port']}{chemin}", corps, info["token"])
    if statut != 200:
        raise DemonIndisponible(f"testd {chemin} : HTTP {statut} {reponse}")
    return reponse


def soumettre(cmd: list[str], env: dict, cwd: str, timeout: int, python: str, cibles=(),
              base: dict | None = None, a_nettoyer=()) -> dict:
    """`cibles` : les `targets` (saut de collecte) ; `base` : {"communs": [...]} pour comparer les
    échecs à la base ; `a_nettoyer` : dossiers temporaires que le démon supprime en fin de job."""
    return _appel("/jobs", {"cmd": cmd, "env": env, "cwd": cwd, "timeout": timeout, "python": python,
                            "cibles": list(cibles), "base": base, "a_nettoyer": list(a_nettoyer)})


def etat(job_id: str) -> dict:
    """État courant ; celui écrit sur disque si le démon ne connaît plus le job (redémarré)."""
    info = assurer_demon()
    statut, reponse = appel_local(f"http://127.0.0.1:{info['port']}/jobs/{job_id}", None, info["token"])
    if statut == 200:
        return reponse
    final = dossier_testd() / "jobs" / job_id / "final.json"
    if final.exists():
        return json.loads(final.read_text(encoding="utf-8"))
    raise DemonIndisponible(f"job inconnu : {job_id}")


def annuler(job_id: str) -> dict:
    return _appel(f"/jobs/{job_id}/cancel", {})


def arreter_demon() -> None:
    """Arrêt propre (tests, maintenance)."""
    info = _lire_info()
    if info:
        appel_local(f"http://127.0.0.1:{info['port']}/shutdown", {}, info["token"])
