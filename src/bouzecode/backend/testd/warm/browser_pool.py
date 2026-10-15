# [desc] testd : un navigateur chaud partagé par version de Playwright (`playwright launch-server`) et la réserve de contextes navigateur de la machine [/desc]
"""Pourquoi `launch-server` et pas `run-server` (vérifié dans le code de Playwright 1.58 et 1.59,
`lib/remote/playwrightServer.js`) : `run-server` en mode `default` LANCE un navigateur à chaque
connexion (`_initLaunchBrowserMode`) — il n'y a rien de chaud — et son mode `extension`, qui
réutilise, sérialise les connexions (sémaphore à 1). `launch-server` lance UN navigateur au
démarrage et le partage entre toutes les connexions (`preLaunchedBrowser`, connexions
illimitées) ; `Browser.close()` côté client ne fait que se déconnecter.

Le client et le serveur doivent avoir la MÊME version : un serveur par version, lancé avec le
python du projet qui le demande.

Navigateur : la coquille headless livrée par CE Playwright (`chromium_headless_shell-<rév>`)
quand elle est installée, Edge système sinon (et le job le lit dans ses notes) ; mesures et
raisons dans `plugin/_bz_pw_lancement.py`. `BZ_TESTD_BROWSER_CHANNEL` impose un canal."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from ..common import sans_fenetre, tuer_arbre
from ..run.split import DOSSIER_PLUGIN

_journal = logging.getLogger("testd")
_DELAI_DEMARRAGE_S = 120


class ReserveDeContextes:
    """Sémaphore pondéré : un sous-run navigateur à k workers prend k contextes."""

    def __init__(self, total: int) -> None:
        self.total = max(1, total)
        self._pris = 0
        self._cond = threading.Condition()

    def prendre(self, nombre: int, abandon) -> bool:
        """Bloque jusqu'à `nombre` contextes libres ; False si `abandon()` devient vrai."""
        nombre = min(nombre, self.total)
        with self._cond:
            while self._pris + nombre > self.total:
                if abandon():
                    return False
                self._cond.wait(0.5)
            self._pris += nombre
            return True

    def rendre(self, nombre: int) -> None:
        with self._cond:
            self._pris -= min(nombre, self.total)
            self._cond.notify_all()


class NavigateursChauds:
    def __init__(self, dossier: Path) -> None:
        self._dossier = dossier
        self._serveurs: dict[str, dict] = {}   # version -> {proc, ws}
        self._sondes: dict[str, dict] = {}     # python -> {version, coquille, attendue}
        self._verrou = threading.Lock()

    def sonde(self, python: str, env: dict) -> dict:
        """Playwright importable par ce python : version ("" : absent), coquille headless installée
        (sa révision, "" sinon) et révision attendue (cf. `plugin/_bz_pw_lancement.py`)."""
        if python not in self._sondes:
            code = (f"import sys, json; sys.path.insert(0, {DOSSIER_PLUGIN!r}); "
                    "import _bz_pw_lancement as l; print(json.dumps(l.sonde()))")
            sortie = subprocess.run([python, "-c", code], capture_output=True, text=True, env=env,
                                    timeout=60, **sans_fenetre())
            self._sondes[python] = (json.loads(sortie.stdout.strip().splitlines()[-1])
                                    if sortie.returncode == 0 else {"version": ""})
        return self._sondes[python]

    def version(self, python: str, env: dict) -> str:
        return self.sonde(python, env)["version"]

    @staticmethod
    def canaux(sonde: dict) -> tuple[list[str], str]:
        """Canaux à essayer dans l'ordre ("" : la coquille livrée) et la note du choix."""
        impose = os.environ.get("BZ_TESTD_BROWSER_CHANNEL")
        if impose is not None:
            return list(dict.fromkeys([impose, ""])), ""
        if sonde["coquille"]:
            return ["", "msedge"], ""
        return ["msedge", ""], (f"[testd] chromium_headless_shell-{sonde['attendue']} absente pour "
                                f"Playwright {sonde['version']} : navigateur chaud sur Edge système.\n")

    def point_d_acces(self, python: str, env: dict) -> tuple[str, object, str]:
        """(ws, process serveur, note) ; ws vide quand aucun navigateur chaud n'est possible."""
        sonde = self.sonde(python, env)
        version = sonde["version"]
        if not version:
            return "", None, "[testd] Playwright absent de ce python : pas de navigateur chaud.\n"
        with self._verrou:
            serveur = self._serveurs.get(version)
            if serveur and serveur["proc"].poll() is None:
                return serveur["ws"], serveur["proc"], ""
            canaux, note = self.canaux(sonde)
            note = ("[testd] navigateur chaud mort : relancé.\n" if serveur else "") + note
            for canal in canaux:
                serveur = self._demarrer(python, env, version, canal)
                if serveur:
                    self._serveurs[version] = serveur
                    return serveur["ws"], serveur["proc"], note
        return "", None, note + f"[testd] navigateur chaud Playwright {version} impossible à lancer.\n"

    def deja_chaud(self, python: str, env: dict) -> str:
        """ws du navigateur chaud de cette version s'il tourne déjà ; "" sinon (rien n'est lancé)."""
        version = self.version(python, env)
        with self._verrou:
            serveur = self._serveurs.get(version) if version else None
            return serveur["ws"] if serveur and serveur["proc"].poll() is None else ""

    def _demarrer(self, python: str, env: dict, version: str, canal: str) -> dict | None:
        options = {"headless": True, "args": ["--no-proxy-server"], "host": "127.0.0.1"}
        if canal:
            options["channel"] = canal
        nom = f"pw-{version}-{canal or 'chromium'}"
        config = self._dossier / f"{nom}.json"
        config.write_text(json.dumps(options), encoding="utf-8")
        sortie = self._dossier / f"{nom}.log"
        with open(sortie, "w", encoding="utf-8") as journal:
            proc = subprocess.Popen(
                [python, "-m", "playwright", "launch-server", "--browser", "chromium",
                 "--config", str(config)],
                stdout=journal, stderr=subprocess.STDOUT, env=env, **sans_fenetre(groupe=True))
        fin = time.monotonic() + _DELAI_DEMARRAGE_S
        while time.monotonic() < fin and proc.poll() is None:
            lignes = [l for l in sortie.read_text(encoding="utf-8", errors="replace").splitlines()
                      if l.startswith("ws://")]
            if lignes:
                _journal.info("navigateur chaud %s : %s (pid %s)", nom, lignes[0], proc.pid)
                return {"proc": proc, "ws": lignes[0]}
            time.sleep(0.2)
        _journal.warning("navigateur chaud %s : échec du démarrage, voir %s", nom, sortie)
        tuer_arbre(proc.pid)
        return None

    def arreter_tout(self) -> None:
        with self._verrou:
            for serveur in self._serveurs.values():
                tuer_arbre(serveur["proc"].pid)
            self._serveurs.clear()
