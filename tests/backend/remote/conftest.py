"""Faux serveurs HTTP locaux : Rundeck (API JSON) et Azure Files (REST, signature non verifiee)."""
import json
import re
import xml.sax.saxutils as saxutils
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread  # serveurs de fond, pas un test de concurrence
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import yaml


class _Base(BaseHTTPRequestHandler):
    def log_message(self, *arguments):
        pass

    def _repondre(self, code: int, corps: bytes = b"", type_contenu: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _corps(self) -> bytes:
        longueur = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(longueur) if longueur else b""

    def do_GET(self):
        self._traiter("GET")

    def do_POST(self):
        self._traiter("POST")

    def do_PUT(self):
        self._traiter("PUT")

    def do_DELETE(self):
        self._traiter("DELETE")

    def do_HEAD(self):
        self._traiter("HEAD")


class FauxRundeck(_Base):
    """Un job `job-1` a la fois ; refuse comme le vrai une option `hidden` sans valeur par defaut."""
    jobs: dict = {}
    appels: list = []
    options_recues: dict = {}
    yaml_importes: list = []
    echouer_lancement = False

    def _json(self, code: int, corps=None):
        self._repondre(code, json.dumps(corps).encode() if corps is not None else b"")

    def _traiter(self, methode: str):
        corps = self._corps()
        FauxRundeck.appels.append((methode, self.path))
        if self.headers.get("X-Rundeck-Auth-Token") != "jeton-test":
            return self._json(403, {"error": True})
        if methode == "POST" and "/jobs/import" in self.path:
            FauxRundeck.yaml_importes.append(corps.decode("utf-8"))
            job = yaml.safe_load(corps)[0]
            invalides = [o["name"] for o in job.get("options", []) if o.get("hidden") and "value" not in o]
            if invalides:
                return self._json(200, {"succeeded": [], "skipped": [], "failed": [
                    {"error": f"Invalid Option definition: {invalides}: Hidden options must have a default value."}]})
            if job["name"] in FauxRundeck.jobs.values():
                return self._json(200, {"succeeded": [], "failed": [], "skipped": [{"name": job["name"]}]})
            FauxRundeck.jobs["job-1"] = job["name"]
            return self._json(200, {"succeeded": [{"id": "job-1", "name": job["name"]}], "failed": [], "skipped": []})
        if methode == "POST" and re.search(r"/job/job-1/run$", self.path):
            if FauxRundeck.echouer_lancement:
                return self._json(500, {"error": True, "message": "panne simulee"})
            FauxRundeck.options_recues = json.loads(corps)["options"]
            return self._json(200, {"id": 77, "permalink": "http://rundeck/execution/77"})
        if methode == "GET" and self.path.endswith("/execution/77"):
            return self._json(200, {"id": 77, "status": "succeeded", "permalink": "http://rundeck/execution/77",
                                    "job": {"id": "job-1"}})
        if methode == "GET" and "/execution/77/output" in self.path:
            return self._json(200, {"entries": [{"log": "ligne 1"}, {"log": "ligne 2"}]})
        if methode == "DELETE" and self.path.endswith("/job/job-1"):
            FauxRundeck.jobs.pop("job-1", None)
            return self._json(204)
        return self._json(404, {"error": True})


class FauxShare(_Base):
    """Azure Files minimal : dossiers, creation de fichier, plages, lecture, liste, suppression."""
    fichiers: dict = {}
    dossiers: set = set()

    def _traiter(self, methode: str):
        url = urlparse(self.path)
        chemin = unquote(url.path).strip("/").split("/", 1)[1] if "/" in unquote(url.path).strip("/") else ""
        requete = {k: v[0] for k, v in parse_qs(url.query).items()}
        corps = self._corps()
        if methode == "PUT" and requete.get("restype") == "directory":
            existe = chemin in FauxShare.dossiers
            FauxShare.dossiers.add(chemin)
            return self._repondre(409 if existe else 201)
        if methode == "PUT" and requete.get("comp") == "range":
            debut = int(self.headers["x-ms-range"].split("=")[1].split("-")[0])
            contenu = FauxShare.fichiers[chemin]
            FauxShare.fichiers[chemin] = contenu[:debut] + corps + contenu[debut + len(corps):]
            return self._repondre(201)
        if methode == "PUT":
            FauxShare.fichiers[chemin] = bytearray(int(self.headers["x-ms-content-length"]))
            return self._repondre(201)
        if methode == "GET" and requete.get("comp") == "list":
            if chemin not in FauxShare.dossiers:
                return self._repondre(404)
            noms = {c[len(chemin) + 1:].split("/")[0] for c in list(FauxShare.fichiers) + list(FauxShare.dossiers)
                    if c.startswith(chemin + "/")}
            enfants = {nom: f"{chemin}/{nom}" in FauxShare.dossiers for nom in noms}
            xml = "".join(f"<{'Directory' if d else 'File'}><Name>{saxutils.escape(n)}</Name></{'Directory' if d else 'File'}>"
                          for n, d in enfants.items())
            return self._repondre(200, f"<EnumerationResults><Entries>{xml}</Entries></EnumerationResults>".encode(),
                                  "application/xml")
        if methode in ("GET", "HEAD"):
            if chemin not in FauxShare.fichiers:
                return self._repondre(404)
            return self._repondre(200, bytes(FauxShare.fichiers[chemin]) if methode == "GET" else b"")
        if methode == "DELETE":
            FauxShare.fichiers.pop(chemin, None)
            FauxShare.dossiers.discard(chemin)
            return self._repondre(202)
        return self._repondre(400)


def _servir(gestionnaire):
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), gestionnaire)
    Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur


@pytest.fixture
def faux_rundeck():
    FauxRundeck.jobs, FauxRundeck.appels, FauxRundeck.options_recues = {}, [], {}
    FauxRundeck.yaml_importes, FauxRundeck.echouer_lancement = [], False
    serveur = _servir(FauxRundeck)
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()


@pytest.fixture
def faux_share():
    FauxShare.fichiers, FauxShare.dossiers = {}, set()
    serveur = _servir(FauxShare)
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()


@pytest.fixture
def etat_faux_rundeck(faux_rundeck):
    """L'etat observe par le faux Rundeck (jobs, options recues, YAML importes)."""
    return FauxRundeck


@pytest.fixture
def etat_faux_share(faux_share):
    """L'etat du faux file share (fichiers, dossiers)."""
    return FauxShare
