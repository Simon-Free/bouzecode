# [desc] testd : serveur applicatif chaud par worktree, décrit par `.bouzecode/tests.yaml` (`app_server:`), relancé quand un fichier surveillé a changé [/desc]
"""Clés lues (les autres, dont `impacted:`, sont ignorées) :

    browser:    {marker: browser}
    app_server: {command: ["{python}", "run.py"], env: {FLASK_RUN_PORT: "{port}"},
                 health_path: /, base_url_env: BZ_APP_BASE_URL, watch: ["src/**/*.py"],
                 test_equivalent: true}

`test_equivalent: true` est OBLIGATOIRE : le projet atteste que `command`/`env` lancent l'appli
dans la configuration des tests (ex. demo : `run.py` charge le vrai `.env` et le vrai LDAP,
alors que `bypass_ldap` ne patche que le process de test). Sans cette attestation, aucun
serveur n'est lancé et la note le dit. `base_url_env` est le nom que lisent les fixtures du
projet (demo : `TEST_BASE_URL`) ; testd n'impose aucun nom.

Le changement de code se détecte par un balayage des mtime avant chaque job : plus simple et
plus sûr qu'un rechargeur dans le process (qui rate les templates ou meurt sur une erreur de
syntaxe). Le serveur n'est jamais relancé sous un job qui l'utilise encore."""
from __future__ import annotations

import logging
import socket
import subprocess
import threading
import time
from pathlib import Path

import yaml

from ..common import appel_local, sans_fenetre, tuer_arbre

_journal = logging.getLogger("testd")
_DELAI_SANTE_S = 60


def config_tests(cwd: str) -> dict:
    """`tests.yaml` le plus proche de `cwd` (`.bouzecode/` puis `.bouzecode/`), {} sinon."""
    from ....paths import project_dirs
    depart = Path(cwd).resolve()
    for dossier in [depart, *depart.parents]:
        for projet in project_dirs(dossier):
            fichier = projet / "tests.yaml"
            if fichier.is_file():
                return {**(yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}),
                        "_racine": str(dossier)}
    return {}


def _port_libre() -> int:
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        return sonde.getsockname()[1]


def _dernier_changement(racine: str, motifs: list[str]) -> float:
    return max((f.stat().st_mtime for motif in motifs for f in Path(racine).glob(motif)
                if f.is_file()), default=0.0)


class ServeursApplicatifs:
    def __init__(self, dossier: Path) -> None:
        self._dossier = dossier
        self._serveurs: dict[str, dict] = {}   # racine -> {proc, url, debut, motifs, usages}
        self._verrou = threading.Lock()

    def prendre(self, config: dict, python: str, env: dict) -> tuple[dict, str]:
        """(variables à exporter au job, note). À rendre par `rendre(config)` après le job."""
        app = config.get("app_server")
        if not app:
            return {}, ""
        if app.get("test_equivalent") is not True:
            return {}, ("[testd] app_server ignoré : tests.yaml n'atteste pas `test_equivalent: true` "
                        "(serveur lancé en configuration de test).\n")
        racine, note = config["_racine"], ""
        with self._verrou:
            serveur = self._serveurs.get(racine)
            if serveur and serveur["usages"] == 0 and (
                    serveur["proc"].poll() is not None
                    or _dernier_changement(racine, serveur["motifs"]) > serveur["debut"]):
                tuer_arbre(serveur["proc"].pid)
                serveur, note = None, "[testd] serveur applicatif relancé (code modifié ou arrêté).\n"
            if not serveur:
                serveur = self._demarrer(racine, app, python, env)
                if not serveur:
                    return {}, note + f"[testd] serveur applicatif de {racine} : démarrage en échec.\n"
                self._serveurs[racine] = serveur
            serveur["usages"] += 1
            return {app.get("base_url_env", "BZ_APP_BASE_URL"): serveur["url"]}, note

    def rendre(self, config: dict) -> None:
        with self._verrou:
            serveur = self._serveurs.get(config.get("_racine", ""))
            if serveur and config.get("app_server"):
                serveur["usages"] -= 1

    def _demarrer(self, racine: str, app: dict, python: str, env: dict) -> dict | None:
        port = _port_libre()
        valeurs = {"python": python, "port": str(port)}
        commande = [str(a).format(**valeurs) for a in app["command"]]
        env_serveur = {**env, **{k: str(v).format(**valeurs) for k, v in (app.get("env") or {}).items()}}
        debut = time.time()
        journal = open(self._dossier / f"app-{port}.log", "w", encoding="utf-8")
        proc = subprocess.Popen(commande, cwd=racine, env=env_serveur, stdout=journal,
                                stderr=subprocess.STDOUT, **sans_fenetre(groupe=True))
        journal.close()  # le process garde sa copie du descripteur
        url = f"http://127.0.0.1:{port}"
        fin = time.monotonic() + _DELAI_SANTE_S
        while time.monotonic() < fin and proc.poll() is None:
            if _repond(url + app.get("health_path", "/")):
                _journal.info("serveur applicatif %s : %s (pid %s)", racine, url, proc.pid)
                return {"proc": proc, "url": url, "debut": debut, "usages": 0,
                        "motifs": list(app.get("watch") or [])}
            time.sleep(0.3)
        tuer_arbre(proc.pid)
        return None

    def arreter_tout(self) -> None:
        with self._verrou:
            for serveur in self._serveurs.values():
                tuer_arbre(serveur["proc"].pid)
            self._serveurs.clear()



def _repond(url: str) -> bool:
    """2xx/3xx = prêt. Personne à l'écoute (OSError) = pas encore prêt."""
    try:
        statut, _ = appel_local(url, delai_s=2)
    except OSError:
        return False
    return statut < 400
