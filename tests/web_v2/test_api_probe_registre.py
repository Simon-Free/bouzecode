# [desc] La sonde de santé API lit ses exigences dans registry.PROVIDERS (source unique) et sonde un vrai serveur local. [/desc]
"""api_probe recopiait la table des fournisseurs (URL OpenRouter redéclarée, clés à la main) :
la copie avait déjà divergé (le gateway prod n'acceptait qu'ANTHROPIC_AUTH_TOKEN alors que
l'agent accepte aussi ANTHROPIC_API_KEY). Elle dérive désormais de registry.PROVIDERS.

Aucun mock : `default_ping` sonde de vrais serveurs HTTP jetables sur la boucle locale.
"""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bouzecode.backend.agent.providers.registry import OPENROUTER_BASE_URL, PROVIDERS
from bouzecode.web_v2 import api_probe


def _no_sleep(_s):
    pass


class _Gateway(BaseHTTPRequestHandler):
    status = 200
    seen: list = []

    def do_GET(self):
        type(self).seen.append(self.path)
        self.send_response(type(self).status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def gateway():
    _Gateway.seen = []
    _Gateway.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _verdict(env, provider):
    return api_probe.verdict(env, api_probe.default_ping, 1, _no_sleep, provider=provider)


@pytest.mark.parametrize("statut", [200, 401])
def test_un_endpoint_qui_repond_est_joignable(gateway, statut):
    _Gateway.status = statut
    ok, detail, base, cle = _verdict({"PREPROD_ENDPOINT": gateway, "OPENAI_API_KEY_PP": "k"},
                                     "gateway_preprod")
    assert (ok, base, cle) == (True, True, True), detail
    assert "gateway préprod" in detail
    assert _Gateway.seen == ["/"]


def test_un_endpoint_eteint_est_injoignable_pas_mal_configure():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    ok, detail, base, cle = _verdict(
        {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}", "ANTHROPIC_API_KEY": "k"}, "anthropic")
    assert (ok, base, cle) == (False, True, True)
    assert "injoignable" in detail


def test_les_exigences_viennent_du_registre():
    for nom, prov in PROVIDERS.items():
        exig = api_probe.exigence(nom)
        assert exig["nom"] == prov["label"]
        assert exig["cles"] == tuple(prov["key_envs"])
    assert api_probe.exigence("openrouter")["url"] == OPENROUTER_BASE_URL
    assert api_probe.exigence("inconnu") == api_probe.exigence("anthropic")


def test_une_cle_ajoutee_au_registre_est_vue_par_la_sonde(monkeypatch, gateway):
    """Une seule source de vérité : changer le registre change le verdict, sans autre copie."""
    monkeypatch.setitem(PROVIDERS["gateway_preprod"], "key_envs", ("NOUVELLE_CLE_PP",))
    env = {"PREPROD_ENDPOINT": gateway, "OPENAI_API_KEY_PP": "k"}

    ok, detail, _base, cle = _verdict(env, "gateway_preprod")
    assert (ok, cle) == (False, False)
    assert "NOUVELLE_CLE_PP" in detail

    ok, _detail, _base, _cle = _verdict({**env, "NOUVELLE_CLE_PP": "k"}, "gateway_preprod")
    assert ok is True


def test_le_gateway_openai_accepte_les_memes_cles_que_l_agent(gateway):
    """L'agent (get_provider_key → get_api_key) accepte ANTHROPIC_API_KEY pour le gateway prod :
    la sonde ne doit plus le déclarer mal configuré."""
    ok, detail, _base, cle = _verdict({"ANTHROPIC_BASE_URL": gateway, "ANTHROPIC_API_KEY": "k"},
                                      "gateway_openai")
    assert (ok, cle) == (True, True), detail
