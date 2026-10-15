# [desc] testd : le serveur applicatif décrit par tests.yaml est démarré une fois, son URL exportée aux jobs du worktree, et relancé quand un fichier surveillé change [/desc]
from __future__ import annotations

import os
import sys
import time

from bouzecode.backend.testd.rendu import attendre
from tests.backend.testd.aides import commande, projet

_FICHIERS = {
    "serveur.py": """
        import os
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class Pid(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(str(os.getpid()).encode())
        HTTPServer(("127.0.0.1", int(os.environ["PORT_APP"])), Pid).serve_forever()
    """,
    "test_appli.py": """
        import os, urllib.request
        def test_appli_repond():
            ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            pid = ouvreur.open(os.environ["BZ_APP_BASE_URL"] + "/").read().decode()
            open("pid_vu.txt", "w").write(pid)
    """,
}
_YAML = """\
impacted: {ignore: this}
app_server:
  command: ["{python}", "serveur.py"]
  env: {PORT_APP: "{port}"}
  health_path: /
  base_url_env: BZ_APP_BASE_URL
  watch: ["*.py"]
  test_equivalent: true
"""


def _job(demon, racine):
    job = demon.soumettre(commande("test_appli.py"), dict(os.environ), str(racine), 60, sys.executable)
    etat = attendre(job["job_id"], 90, au_premier_echec=False)
    assert etat["passed"] == 1, etat
    return (racine / "pid_vu.txt").read_text(), etat["notes"]


def test_serveur_chaud_reutilise_puis_relance_apres_modification(demon, tmp_path):
    racine = projet(tmp_path / "p", _FICHIERS)
    (racine / ".bouzecode").mkdir()
    (racine / ".bouzecode" / "tests.yaml").write_text(_YAML, encoding="utf-8")

    premier, _ = _job(demon, racine)
    second, notes = _job(demon, racine)
    assert second == premier and "relancé" not in notes

    futur = time.time() + 5
    os.utime(racine / "serveur.py", (futur, futur))
    troisieme, notes = _job(demon, racine)
    assert troisieme != premier and "relancé" in notes


def test_sans_attestation_aucun_serveur_n_est_lance(demon, tmp_path):
    racine = projet(tmp_path / "p", {"test_ok.py": "def test_ok():\n    assert True\n"})
    (racine / ".bouzecode").mkdir()
    sans_attestation = _YAML.replace("  test_equivalent: true\n", "")
    (racine / ".bouzecode" / "tests.yaml").write_text(sans_attestation, encoding="utf-8")
    job = demon.soumettre(commande("test_ok.py"), dict(os.environ), str(racine), 60, sys.executable)
    etat = attendre(job["job_id"], 60, au_premier_echec=False)
    assert etat["passed"] == 1 and "test_equivalent" in etat["notes"]
