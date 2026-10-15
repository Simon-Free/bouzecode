# [desc] testd : le démon de tests de la machine — serveur HTTP local (jeton), file des jobs, navigateurs et serveurs chauds, arrêt après inactivité [/desc]
"""`python -m bouzecode.backend.testd.daemon [--detach]`.

IPC = HTTP sur 127.0.0.1, port éphémère, publié avec un jeton dans `daemon.json` (dossier de
l'utilisateur). Choisi plutôt que des fichiers : sous Windows, un fichier qu'un autre process
lit pendant qu'on le réécrit lève PermissionError, et le sondage de fichiers ajoute de la
latence ; la stdlib suffit des deux côtés (http.server / urllib sans proxy).

`--detach` relance le démon par un process intermédiaire qui sort aussitôt : sans parent
vivant, le démon n'est pas emporté par le `taskkill /T` qui tue l'agent qui l'a démarré."""
from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from .common import (appel_local, console_visible, dossier_testd, lacher_console_visible,
                     options_demon, reglages)
from .budget.creneaux import CreneauxNavigateur
from .budget.workers import BudgetWorkers
from .run.scheduler import Ordonnanceur
from .warm.app_servers import ServeursApplicatifs
from .warm.browser_pool import NavigateursChauds, ReserveDeContextes
from .warm.prechauffage import Prechauffage

_journal = logging.getLogger("testd")


def _gestionnaire(ordonnanceur: Ordonnanceur, jeton: str, arreter):
    class Gestionnaire(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return  # le journal du démon suffit

        def _repondre(self, statut: int, corps: dict) -> None:
            donnees = json.dumps(corps).encode("utf-8")
            self.send_response(statut)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(donnees)))
            self.end_headers()
            self.wfile.write(donnees)

        def _route(self, methode: str) -> None:
            if self.path != "/health" and self.headers.get("X-BZ-Token") != jeton:
                return self._repondre(403, {"error": "jeton invalide"})
            ordonnanceur.derniere_activite = time.time()
            morceaux = self.path.strip("/").split("/")
            if self.path == "/health":
                return self._repondre(200, {"pid": os.getpid(), "console_visible": console_visible()})
            if methode == "POST" and self.path == "/shutdown":
                threading.Thread(target=arreter, daemon=True).start()
                return self._repondre(200, {"ok": True})
            if methode == "POST" and self.path == "/jobs":
                longueur = int(self.headers.get("Content-Length", 0))
                demande = json.loads(self.rfile.read(longueur))
                job = ordonnanceur.soumettre(demande["cmd"], demande["env"], demande["cwd"],
                                             int(demande["timeout"]), demande["python"],
                                             demande.get("cibles", ()), demande.get("base"),
                                             demande.get("a_nettoyer", ()))
                return self._repondre(200, {"job_id": job.id, "position": ordonnanceur.position(job)})
            job = ordonnanceur.jobs.get(morceaux[1]) if len(morceaux) >= 2 and morceaux[0] == "jobs" else None
            if job is None:
                return self._repondre(404, {"error": f"job inconnu : {self.path}"})
            if methode == "GET" and morceaux[2:] == ["navigateur"]:
                return self._repondre(200, ordonnanceur.navigateur(job))
            if methode == "POST" and morceaux[2:] == ["cancel"]:
                ordonnanceur.annuler(job)
            return self._repondre(200, ordonnanceur.instantane(job))

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Gestionnaire


def servir() -> None:
    dossier = dossier_testd()
    logging.basicConfig(filename=dossier / "daemon.log", level=logging.INFO,
                        format="%(asctime)s %(process)d %(levelname)s %(message)s")
    if _demon_vivant(dossier):
        _journal.info("un démon répond déjà : sortie")
        return
    valeurs = reglages()
    ressources = SimpleNamespace(workers=BudgetWorkers(valeurs["workers_total"]),
                                 contextes=ReserveDeContextes(valeurs["browser_slots"]),
                                 creneaux=CreneauxNavigateur(valeurs["browser_jobs"]),
                                 navigateurs=NavigateursChauds(dossier),
                                 applis=ServeursApplicatifs(dossier), prechauffage=Prechauffage())
    ordonnanceur = Ordonnanceur(ressources, dossier)
    jeton = secrets.token_hex(16)
    fin = threading.Event()
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _gestionnaire(ordonnanceur, jeton, fin.set))
    serveur.daemon_threads = True
    #  Le plugin `_bz_pw_patch` d'un job demande ici le navigateur chaud à sa première utilisation.
    ressources.demande = (f"http://127.0.0.1:{serveur.server_address[1]}", jeton)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    fichier = dossier / "daemon.json"
    provisoire = dossier / f"daemon.{os.getpid()}.tmp"
    provisoire.write_text(json.dumps({"pid": os.getpid(), "port": serveur.server_address[1],
                                      "token": jeton, "started": time.time()}), encoding="utf-8")
    os.replace(provisoire, fichier)
    _journal.info("démon prêt : port %s, réglages %s", serveur.server_address[1], valeurs)
    while not fin.wait(1.0):
        if ordonnanceur.inactif_depuis() > valeurs["idle_s"]:
            _journal.info("inactif depuis %s s : arrêt", valeurs["idle_s"])
            break
    serveur.shutdown()
    ordonnanceur.tout_annuler()
    ressources.navigateurs.arreter_tout()
    ressources.applis.arreter_tout()
    if fichier.exists() and json.loads(fichier.read_text(encoding="utf-8"))["pid"] == os.getpid():
        fichier.unlink()
    _journal.info("démon arrêté")


def _demon_vivant(dossier) -> bool:
    fichier = dossier / "daemon.json"
    if not fichier.exists():
        return False
    info = json.loads(fichier.read_text(encoding="utf-8"))
    try:
        statut, _ = appel_local(f"http://127.0.0.1:{info['port']}/health", delai_s=3)
    except OSError:
        return False
    return statut == 200


def detacher() -> None:
    """Relance `servir` sans parent vivant (cf. docstring du module), puis sort."""
    python, options = options_demon()
    if sys.platform == "win32":
        options["creationflags"] |= subprocess.CREATE_BREAKAWAY_FROM_JOB
    commande = [python, "-m", "bouzecode.backend.testd.daemon"]
    try:
        subprocess.Popen(commande, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **options)
    except OSError:  # job Windows qui interdit la sortie : on reste dedans
        options["creationflags"] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB
        subprocess.Popen(commande, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **options)


if __name__ == "__main__":
    lacher_console_visible()
    detacher() if "--detach" in sys.argv else servir()
