# [desc] Les E2E du bac à sable joignent le jeton du serveur VISÉ (lu dans sa page) à leurs mutations : 401 sans, accepté avec. [/desc]
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest
from werkzeug.serving import make_server

from bouzecode.web_v2 import app as web_app
from bouzecode.web_v2.tests.e2e_sandbox import jeton_e2e


@pytest.fixture()
def serveur():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    srv = make_server("127.0.0.1", port, web_app.create_app())
    fil = threading.Thread(target=srv.serve_forever, daemon=True)
    fil.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    fil.join(timeout=5)


def _post(base: str, chemin: str, en_tetes: dict) -> int:
    req = urllib.request.Request(base + chemin, data=json.dumps({"titre": "e2e"}).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json", **en_tetes})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as erreur:
        return erreur.code


def test_le_jeton_lu_dans_la_page_ouvre_les_mutations(serveur):
    jeton_e2e.jeton_du_serveur.cache_clear()
    assert _post(serveur, "/api/macros", {}) == 401
    assert jeton_e2e.en_tetes(serveur, "GET") == {}
    assert _post(serveur, "/api/macros", jeton_e2e.en_tetes(serveur, "POST")) == 201
