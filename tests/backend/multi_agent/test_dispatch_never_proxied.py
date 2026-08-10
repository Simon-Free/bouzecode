"""Un dispatch LOCAL atteint le serveur bouzecode même quand l'environnement pose un
proxy d'entreprise et que `NO_PROXY` ne couvre pas la boucle locale.

Panne du 2026-07-28 : le dispatch d'un manager partait dans le proxy et revenait en
`HTTP Error 407: Proxy Authentication Required`, sans qu'aucun ticket ne soit créé.

Aucun mock : deux vrais serveurs HTTP jetables sur la boucle locale — le serveur bouzecode
simulé, et un proxy qui répond 407 à tout et compte ce qu'il reçoit. Si la requête part
dans le proxy, elle est vue ; si elle n'y part pas, le compteur reste à zéro.
"""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bouzecode.backend.core.local_http import LocalServerError, local_json
from bouzecode.backend.multi_agent import tools

DISPATCHED = {"routed": True, "ticket_id": "t-42", "project_slug": "p", "typology": "coder"}


class _BouzecodeServer(BaseHTTPRequestHandler):
    """Le serveur bouzecode : route /api/dispatch, 404 (avec motif) sur le reste."""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._reply(200, DISPATCHED) if self.path == "/api/dispatch" \
            else self._reply(404, {"error": "route inconnue"})

    def do_GET(self):
        # /api/407 rejoue ce que voyait le manager en production : un 407 rendu sur une URL
        # LOCALE, parce qu'un proxy avait intercepté la requête en chemin.
        self._reply(407, {}) if self.path == "/api/407" \
            else self._reply(404, {"error": "route inconnue"})

    def _reply(self, code, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class _Proxy407(BaseHTTPRequestHandler):
    """Le proxy d'entreprise : 407 sur tout, et il note chaque requête reçue."""

    seen: list = []

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._deny()

    def do_GET(self):
        self._deny()

    def _deny(self):
        type(self).seen.append(self.path)
        self.send_response(407, "Proxy Authentication Required")
        self.send_header("Proxy-Authenticate", "Negotiate")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def bouzecode_server():
    server, url = _serve(_BouzecodeServer)
    yield url
    server.shutdown()


@pytest.fixture
def proxy():
    _Proxy407.seen = []
    server, url = _serve(_Proxy407)
    yield url
    server.shutdown()


# Trois environnements réels, chacun à UNE variable près du nominal, tous vus en production.
HOSTILE_NO_PROXY = {
    "NO_PROXY absent": None,
    "NO_PROXY ne couvre pas la boucle locale": "example.com",
    "NO_PROXY ne couvre que le nom, pas l'IP appelée": "localhost",
}


def _pose_un_proxy(monkeypatch, proxy_url, no_proxy):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", proxy_url)
    monkeypatch.setenv("HTTPS_PROXY", proxy_url)
    if no_proxy is not None:
        monkeypatch.setenv("NO_PROXY", no_proxy)


@pytest.mark.parametrize("no_proxy", HOSTILE_NO_PROXY.values(), ids=list(HOSTILE_NO_PROXY))
def test_le_dispatch_atteint_le_serveur_local_malgre_le_proxy(
        monkeypatch, bouzecode_server, proxy, no_proxy):
    """Le manager dispatche : la requête va au serveur, jamais au proxy."""
    _pose_un_proxy(monkeypatch, proxy, no_proxy)
    monkeypatch.setattr(tools, "_DISPATCH_URL", f"{bouzecode_server}/api/dispatch")

    # Témoin : dans CE même environnement, un client urllib ordinaire (ce que faisait le
    # dispatch avant le correctif) part dans le proxy et se fait 407 — la panne, rejouée.
    with pytest.raises(urllib.error.HTTPError) as ordinaire:
        urllib.request.build_opener().open(f"{bouzecode_server}/api/dispatch", b"{}")
    assert ordinaire.value.code == 407
    assert _Proxy407.seen == [f"{bouzecode_server}/api/dispatch"]
    _Proxy407.seen.clear()   # on repart d'un proxy vierge pour observer le VRAI dispatch

    assert tools._default_web_dispatch({"prompt": "construis X"}) == DISPATCHED
    assert _Proxy407.seen == []   # le proxy n'a RIEN vu passer du dispatch


def test_un_407_accuse_le_proxy_et_un_404_accuse_le_serveur(
        monkeypatch, bouzecode_server, proxy):
    """« 407 » seul n'apprenait rien : le message doit dire QUI a refusé."""
    _pose_un_proxy(monkeypatch, proxy, None)

    with pytest.raises(LocalServerError) as parti_dans_le_proxy:
        local_json("GET", f"{bouzecode_server}/api/407")
    diagnostic = str(parti_dans_le_proxy.value)
    assert "PARTIE DANS UN PROXY" in diagnostic
    assert "RIEN n'a été créé" in diagnostic
    assert "HTTP_PROXY" in diagnostic          # nomme la variable fautive…
    assert proxy not in diagnostic             # …sans jamais divulguer sa valeur

    with pytest.raises(LocalServerError) as refuse_par_le_serveur:
        local_json("GET", f"{bouzecode_server}/api/inconnu")
    refus = str(refuse_par_le_serveur.value)
    assert "REFUSÉ" in refus and "404" in refus
    assert "route inconnue" in refus           # le motif du serveur remonte
    assert "PARTIE DANS UN PROXY" not in refus  # et le proxy n'est PAS accusé à tort


def test_un_serveur_local_eteint_ne_ressemble_pas_a_un_refus(monkeypatch, proxy):
    """Serveur arrêté → message « injoignable », distinct d'un refus applicatif."""
    _pose_un_proxy(monkeypatch, proxy, None)
    server, url = _serve(_BouzecodeServer)
    server.shutdown()
    server.server_close()

    with pytest.raises(LocalServerError) as injoignable:
        local_json("GET", f"{url}/api/dispatch", timeout=5)
    assert "INJOIGNABLE" in str(injoignable.value)
    assert _Proxy407.seen == []


def test_un_agent_efface_du_serveur_le_lit_en_clair(monkeypatch):
    """Troisième cause, distincte des deux autres : le serveur ne connaît plus l'appelant.

    Le manager doit lire sa propre disparition, pas « aucun projet ouvert » — c'est ce qui
    a fait chercher une erreur de configuration pendant des heures le 2026-07-28."""
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr.ipc")
    config = {"_web_dispatch": lambda body: {
        "needs_project": True, "parent_unknown": True,
        "suggestions": [{"slug": "demo-app", "name": "Demo App"}]}}

    out = tools._spawn_web_ticket_agent({"prompt": "construis X"}, config)

    assert "NE TE CONNAÎT PLUS" in out
    assert "NI un proxy" in out
    assert "demo-app" in out                    # la sortie de secours est nommée
    assert config.get("_bg_agent_launched") is not True   # aucun enfant en vol
