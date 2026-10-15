# [desc] Faux Rundeck + faux Azure Files sur un serveur HTTP local, dont le « run » d'un job joue VRAIMENT le paquet avec vm_runner (la VM, en local). [/desc]
"""Un seul serveur sert les deux API que `bouzecode.remote` appelle :

* `/api/40/...` : Rundeck (import du job `BZ_<run_id>`, lancement, etat, journal, suppression) ;
* `/<share>/...` : Azure Files (dossiers, depot par plages, lecture, listing XML, suppression).

Lancer un job execute le paquet depose sur le faux share avec `vm_runner.executer_paquet` (le
code de la VM) puis depose le dossier resultat sur le share : le cycle complet tourne pour de
vrai, seule la machine change. `ServeurRundeck.commande_vm` remplace la commande du manifeste
(la VM a son `uv` ; le poste de test, non) ; `panne` simule une VM tombee sans resultat ;
`attentes` = nombre de lectures d'etat rendues `running` avant l'issue.
"""
from __future__ import annotations

import json
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread  # serveur de fond, pas un test de concurrence
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from bouzecode.remote.transport.settings import FILESHARE_RACINE
from bouzecode.remote.vm.vm_runner import executer_paquet

SHARE = "share"


class ServeurRundeck:
    def __init__(self) -> None:
        self.fichiers: dict[str, bytes] = {}
        self.dossiers: set[str] = set()
        self.jobs: dict[str, str] = {}
        self.executions: dict[str, dict] = {}
        self.lectures_etat = 0
        self.commande_vm = ""
        self.panne = False
        self.attentes = 1
        self.manifestes: list[dict] = []

    # --------------------------------------------------------------- la « VM »
    def _jouer(self, run_id: str) -> int | str:
        racine = f"{FILESHARE_RACINE}/{run_id}"
        with tempfile.TemporaryDirectory(prefix="bz_vm_") as temporaire:
            base = Path(temporaire)
            paquet = base / "paquet"
            paquet.mkdir()
            for chemin, contenu in self.fichiers.items():
                if chemin.startswith(f"{racine}/paquet/"):
                    (paquet / chemin.rsplit("/", 1)[1]).write_bytes(contenu)
            manifeste = json.loads((paquet / "manifeste.json").read_text(encoding="utf-8"))
            self.manifestes.append(dict(manifeste))
            if self.commande_vm:
                manifeste["commande"] = self.commande_vm
                (paquet / "manifeste.json").write_text(json.dumps(manifeste), encoding="utf-8")
            bilan = executer_paquet(paquet, base / "travail", base / "resultat")
            for fichier in (base / "resultat").rglob("*"):
                if fichier.is_file():
                    relatif = fichier.relative_to(base / "resultat").as_posix()
                    self._poser(f"{racine}/resultat/{relatif}", fichier.read_bytes())
        return bilan["code"]

    def _poser(self, chemin: str, contenu: bytes) -> None:
        self.fichiers[chemin] = contenu
        morceaux = chemin.split("/")[:-1]
        self.dossiers.update("/".join(morceaux[:i]) for i in range(1, len(morceaux) + 1))

    def lancer(self, job_id: str) -> dict:
        run_id = self.jobs[job_id].removeprefix("BZ_")
        code = "panne" if self.panne else self._jouer(run_id)
        execution_id = str(100 + len(self.executions))
        self.executions[execution_id] = {"job": job_id, "attentes": self.attentes,
                                         "statut": "succeeded" if code == 0 else "failed"}
        return {"id": int(execution_id), "permalink": f"http://rundeck/execution/{execution_id}"}

    def etat(self, execution_id: str) -> dict:
        self.lectures_etat += 1
        execution = self.executions[execution_id]
        statut = "running" if execution["attentes"] > 0 else execution["statut"]
        execution["attentes"] -= 1
        return {"id": int(execution_id), "status": statut, "job": {"id": execution["job"]},
                "permalink": f"http://rundeck/execution/{execution_id}"}

    # --------------------------------------------------------------- le « share »
    def lister(self, dossier: str) -> bytes | None:
        if dossier not in self.dossiers:
            return None
        enfants: dict[str, bool] = {}
        for chemin in list(self.fichiers) + list(self.dossiers):
            if chemin.startswith(dossier + "/"):
                reste = chemin[len(dossier) + 1:]
                nom = reste.split("/")[0]
                enfants[nom] = enfants.get(nom, False) or "/" in reste or chemin in self.dossiers
        entrees = "".join(f"<{'Directory' if d else 'File'}><Name>{n}</Name></{'Directory' if d else 'File'}>"
                          for n, d in sorted(enfants.items()))
        return f"<EnumerationResults><Entries>{entrees}</Entries></EnumerationResults>".encode()


def _gestionnaire(etat: ServeurRundeck):
    class Gestionnaire(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def _repondre(self, code: int, corps: bytes | dict = b"") -> None:
            donnees = json.dumps(corps).encode() if isinstance(corps, dict) else corps
            self.send_response(code)
            self.send_header("Content-Length", str(len(donnees)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(donnees)

        def _traiter(self) -> None:
            url = urlparse(self.path)
            corps = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if url.path.startswith("/api/40/"):
                return self._rundeck(url.path[len("/api/40"):], corps)
            chemin = unquote(url.path).removeprefix(f"/{SHARE}/").strip("/")
            return self._share(chemin, parse_qs(url.query), corps)

        def _rundeck(self, chemin: str, corps: bytes) -> None:
            if self.command == "POST" and chemin.endswith("/jobs/import"):
                job_id = f"job-{len(etat.jobs) + 1}"
                etat.jobs[job_id] = yaml.safe_load(corps)[0]["name"]
                return self._repondre(200, {"succeeded": [{"id": job_id}], "failed": [], "skipped": []})
            trouve = re.fullmatch(r"/job/(job-\d+)/run", chemin)
            if self.command == "POST" and trouve:
                return self._repondre(200, etat.lancer(trouve.group(1)))
            trouve = re.fullmatch(r"/execution/(\d+)(/output)?", chemin)
            if self.command == "GET" and trouve and trouve.group(2):
                return self._repondre(200, {"entries": [{"log": "vm: fin du job"}]})
            if self.command == "GET" and trouve:
                return self._repondre(200, etat.etat(trouve.group(1)))
            if self.command == "DELETE" and chemin.startswith("/job/"):
                etat.jobs.pop(chemin.rsplit("/", 1)[1], None)
                return self._repondre(204)
            return self._repondre(404, {"error": True})

        def _share(self, chemin: str, requete: dict, corps: bytes) -> None:
            dossier = requete.get("restype") == ["directory"]
            if self.command == "PUT" and dossier:
                etat.dossiers.add(chemin)
                return self._repondre(201)
            if self.command == "PUT" and requete.get("comp") == ["range"]:
                debut = int(self.headers["x-ms-range"].split("=")[1].split("-")[0])
                existant = etat.fichiers[chemin]
                etat.fichiers[chemin] = existant[:debut] + corps + existant[debut + len(corps):]
                return self._repondre(201)
            if self.command == "PUT":
                etat._poser(chemin, b"\0" * int(self.headers["x-ms-content-length"]))
                return self._repondre(201)
            if self.command == "GET" and dossier:
                liste = etat.lister(chemin)
                return self._repondre(404) if liste is None else self._repondre(200, liste)
            if self.command in ("GET", "HEAD"):
                return self._repondre(200, etat.fichiers[chemin]) if chemin in etat.fichiers \
                    else self._repondre(404)
            if self.command == "DELETE":
                etat.fichiers.pop(chemin, None)
                etat.dossiers.discard(chemin)
                return self._repondre(202)
            return self._repondre(405)

        do_GET = do_PUT = do_POST = do_DELETE = do_HEAD = _traiter

    return Gestionnaire


def demarrer(monkeypatch) -> tuple[ServeurRundeck, ThreadingHTTPServer]:
    """Demarre le faux serveur et pointe `bouzecode.remote` dessus (variables d'environnement)."""
    etat = ServeurRundeck()
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _gestionnaire(etat))
    Thread(target=serveur.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{serveur.server_address[1]}"
    for nom, valeur in {"BOUZECODE_RUNDECK_URL": url, "RUNDECK_PRIVATE_TOKEN_REC": "jeton-test",
                        "AZURE_PRIVATE_TOKEN_REC": "Y2xlZi10ZXN0", "AZURE_FILESHARE_URL": url,
                        "AZURE_FILESHARE_NAME": SHARE, "TRUSTED_HOST": "artifactory.invalid"}.items():
        monkeypatch.setenv(nom, valeur)
    return etat, serveur
