# [desc] /doctor teste le fournisseur réellement configuré pour la session, par la voie commune des appels LLM, contre de faux serveurs locaux. [/desc]
"""Bug : `/doctor` faisait un POST écrit à la main vers https://api.anthropic.com/v1/messages,
en ignorant ANTHROPIC_BASE_URL — il testait un endpoint que la session n'utilise pas et
déclarait « KO » un endpoint compatible Anthropic parfaitement fonctionnel.

Désormais un appel minimal passe par `get_streamer()` → `dispatch.stream` avec le modèle de la
session. Aucun mock : de vrais serveurs HTTP jetables sur la boucle locale, aucun réseau réel.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bouzecode.backend.agent.providers.registry import PROVIDERS
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.commands.info import diagnostics
from tests import cache_conversation_helpers as cch
from tests.mock_anthropic_server import start_mock_anthropic

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mock_api e2e hangs on Windows (threaded werkzeug + httpx streaming)",
)

CLAUDE = "claude-sonnet-4-6"


@pytest.fixture
def anthropic_local(monkeypatch):
    """Un faux endpoint compatible Anthropic, désigné par ANTHROPIC_BASE_URL."""
    def _start(responses):
        url, app = start_mock_anthropic(responses)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        monkeypatch.setattr(cch, "LIVE_API_ALLOWED", True)  # serveur local, pas le gateway
        return app
    return _start


def test_la_sonde_atteint_l_endpoint_configure_avec_le_modele_de_la_session(anthropic_local):
    app = anthropic_local(["OK"])

    r = diagnostics.sonder_fournisseur({"model": CLAUDE, "anthropic_api_key": "k-test"})

    assert r["erreur"] is None
    assert (r["fournisseur"], r["modele"], r["reponse"]) == ("anthropic", CLAUDE, "OK")
    assert r["latence_s"] >= 0
    # L'appel est arrivé sur l'endpoint CONFIGURÉ (pas api.anthropic.com), un seul, minimal.
    assert len(app.recorded_calls) == 1
    appel = app.recorded_calls[0]
    assert appel["model"] == CLAUDE
    assert appel["max_tokens"] <= 64
    assert "tools" not in appel


def test_un_refus_du_fournisseur_est_rapporte_avec_le_fournisseur_et_le_modele(anthropic_local):
    anthropic_local([{"status": 404}])

    r = diagnostics.sonder_fournisseur({"model": CLAUDE, "anthropic_api_key": "k-test"})

    assert r["reponse"] is None
    assert "404" in r["erreur"]
    assert (r["fournisseur"], r["modele"]) == ("anthropic", CLAUDE)


def test_cmd_doctor_affiche_le_resultat_de_l_appel_reel_sans_la_cle(anthropic_local, capsys):
    app = anthropic_local(["OK"])

    diagnostics.cmd_doctor("", None, {"model": CLAUDE, "anthropic_api_key": "k-secrete-1234"})

    sortie = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert f"[PASS] LLM call anthropic / {CLAUDE}" in sortie
    assert len(app.recorded_calls) == 1
    assert "k-secrete" not in sortie and "1234" not in sortie


class _GatewayOpenAI(BaseHTTPRequestHandler):
    """Faux gateway OpenAI-compatible : /v1/chat/completions en SSE, note chaque requête."""

    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        type(self).seen.append((self.path, body))
        chunks = [
            {"choices": [{"delta": {"content": "OK"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
        ]
        raw = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        data = raw.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_un_fournisseur_openai_compatible_est_teste_par_la_meme_voie(monkeypatch):
    """La sonde ne connaît aucun protocole : c'est dispatch qui route. Ici le gateway préprod."""
    _GatewayOpenAI.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setitem(PROVIDERS["gateway_preprod"], "base_url", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("OPENAI_API_KEY_PP", "k-test")

        r = diagnostics.sonder_fournisseur({"model": "mistral-medium-3-5"})
    finally:
        server.shutdown()

    assert r["erreur"] is None, r
    assert (r["fournisseur"], r["reponse"]) == ("gateway_preprod", "OK")
    assert [path for path, _ in _GatewayOpenAI.seen] == ["/v1/chat/completions"]
    assert _GatewayOpenAI.seen[0][1]["model"] == "mistral-medium-3-5"


def test_un_fournisseur_muet_ne_bloque_pas_doctor():
    """Les retries du transport peuvent durer des minutes : /doctor rend la main au délai."""
    def _muet(_raw):
        def _stream(**_kwargs):
            time.sleep(5)
            yield from ()
        return _stream

    set_stream_interceptor(_muet)
    try:
        debut = time.monotonic()
        r = diagnostics.sonder_fournisseur({"model": CLAUDE}, deadline=0.3)
    finally:
        set_stream_interceptor(None)

    assert time.monotonic() - debut < 3
    assert "pas de réponse" in r["erreur"]
