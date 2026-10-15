# [desc] Compteurs de tokens jamais à zéro : flux SSE enregistrés de chaque fournisseur (Anthropic direct, gateway LiteLLM, OpenRouter, gateway préprod) rejoués dans la vraie boucle. [/desc]
"""Du 21 au 25/09, des dizaines de sessions du poste Windows ont fini à in=0 / out=0 : le
client raccrochait sur la fermeture du lot d'appels (`</tool_calls>`) AVANT le chunk qui
porte l'usage. Sur le internal LLM gateway (pass-through Anthropic de LiteLLM) `message_start.usage`
est tout à zéro et l'usage ne circule que dans `message_delta` ; sur un endpoint
OpenAI-compatible il n'arrive que dans le DERNIER chunk. Raccrocher tôt = tout à zéro.

Chaque test fait tourner le VRAI pipeline (dispatch, streamer, parser XML, boucle,
comptabilité) sur un flux enregistré (usage_sse/*.sse), et échoue si un appel journalisé
compte 0 en entrée ou en sortie. Quand le flux s'arrête sans usage, le compte doit être
ESTIMÉ et marqué comme tel (`api_input_estimated` / `api_output_estimated`)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.e2e_harness import bouzecode

FLUX = Path(__file__).parent / "usage_sse"


def _flux(nom: str) -> str:
    return (FLUX / nom).read_text(encoding="utf-8")


def _appels(result):
    return [e for e in result.state.compaction_log if e.get("event") == "llm_call"]


def _aucun_zero(result):
    appels = _appels(result)
    assert appels, "aucun appel LLM journalisé"
    for a in appels:
        assert a["api_input_tokens"] > 0, f"entrée à 0 : {a}"
        assert a["api_output_tokens"] > 0, f"sortie à 0 : {a}"
    state = result.state
    assert state.total_input_tokens == sum(a["api_input_tokens"] for a in appels)
    assert state.total_output_tokens == sum(a["api_output_tokens"] for a in appels)
    return appels


# ── Anthropic (API officielle et gateway LiteLLM), vrai serveur HTTP local ──────────────

sans_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mock_api e2e hangs on Windows (threaded werkzeug + httpx streaming)",
)


def _anthropic(nom: str):
    return bouzecode(["note ça"], mock_api=[{"raw_sse": _flux(nom)},
                                            {"raw_sse": _flux("anthropic_final.sse")}])


@sans_windows
def test_anthropic_officiel_usage_de_message_start_et_message_delta():
    premier = _aucun_zero(_anthropic("anthropic_direct.sse"))[0]
    assert premier["api_output_tokens"] == 87
    assert premier["api_cache_read"] == 9000
    assert not premier.get("api_input_estimated")
    assert not premier.get("api_output_estimated")


@sans_windows
def test_gateway_litellm_usage_seulement_dans_message_delta_apres_le_lot():
    """Le cas des sessions à zéro : message_start vide, tout l'usage après </tool_calls>."""
    premier = _aucun_zero(_anthropic("anthropic_gateway.sse"))[0]
    assert premier["api_input_tokens"] == 4321
    assert premier["api_output_tokens"] == 95
    assert premier["api_cache_read"] == 17000
    assert not premier.get("api_input_estimated")


@sans_windows
def test_gateway_flux_ferme_apres_le_lot_sans_usage_est_estime_et_marque():
    premier = _aucun_zero(_anthropic("anthropic_gateway_coupe.sse"))[0]
    assert premier.get("api_input_estimated") is True
    assert premier.get("api_output_estimated") is True


@sans_windows
def test_gateway_modele_bavard_apres_le_lot_est_estime_et_marque():
    """Le client ne lit pas indéfiniment ce que le modèle écrit après son lot : passé le
    budget d'attente, il raccroche — l'usage manquant est alors estimé, pas mis à 0."""
    premier = _aucun_zero(_anthropic("anthropic_gateway_bavard.sse"))[0]
    assert premier.get("api_input_estimated") is True


# ── OpenAI-compatibles (OpenRouter, gateway préprod) : session HTTP rejouée ─────────────

class _Reponse:
    ok = True
    status_code = 200
    text = ""
    encoding = "utf-8"

    def __init__(self, corps: str, casse_apres: int | None = None):
        self._lignes = corps.splitlines()
        self._casse_apres = casse_apres

    def iter_lines(self, decode_unicode=False):
        for i, ligne in enumerate(self._lignes):
            if self._casse_apres is not None and i >= self._casse_apres:
                import requests
                raise requests.exceptions.ChunkedEncodingError("connexion coupée")
            yield ligne


class _Session:
    def __init__(self, reponses):
        self.reponses = list(reponses)

    def post(self, url, **kwargs):
        return self.reponses.pop(0)


def _openai(monkeypatch, model, reponses, **config):
    from bouzecode.backend.agent.providers.backends import openrouter_stream, openrouter_transport
    from bouzecode.backend.agent.providers import registry
    session = _Session(reponses)
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    monkeypatch.setenv("OPENAI_API_KEY_PP", "sk-pp-test")
    monkeypatch.setitem(registry.PROVIDERS["gateway_preprod"], "base_url", "http://gateway-pp.invalid")
    monkeypatch.setattr(openrouter_stream, "_build_session", lambda: session)
    monkeypatch.setattr(openrouter_transport, "build_plain_session", lambda: session)
    monkeypatch.setattr(openrouter_stream, "_sleep", lambda s: None)
    return bouzecode(["note ça"], config_overrides={"model": model, **config})


def test_openrouter_outils_natifs_usage_du_dernier_chunk(monkeypatch):
    result = _openai(monkeypatch, "deepseek-v4-flash", [
        _Reponse(_flux("openrouter_natif.sse")), _Reponse(_flux("openai_final.sse"))])
    premier = _aucun_zero(result)[0]
    assert premier["api_input_tokens"] == 1000  # 7000 − 6000 lus en cache
    assert premier["api_cache_read"] == 6000
    assert premier["api_output_tokens"] == 140


def test_openrouter_xml_usage_apres_la_fermeture_du_lot(monkeypatch):
    result = _openai(monkeypatch, "deepseek-v4-flash", [
        _Reponse(_flux("openrouter_xml.sse")), _Reponse(_flux("openai_final.sse"))],
        xml_tools=True)
    premier = _aucun_zero(result)[0]
    assert premier["api_output_tokens"] == 140
    assert not premier.get("api_input_estimated")


def test_openrouter_flux_ferme_sans_chunk_d_usage_est_estime_et_marque(monkeypatch):
    result = _openai(monkeypatch, "deepseek-v4-flash", [
        _Reponse(_flux("openrouter_xml_coupe.sse")), _Reponse(_flux("openai_final.sse"))],
        xml_tools=True)
    premier = _aucun_zero(result)[0]
    assert premier.get("api_input_estimated") is True
    assert premier.get("api_output_estimated") is True


def test_openrouter_connexion_coupee_en_vol_apres_du_texte_est_estimee(monkeypatch):
    """Relances épuisées, une coupure après du texte remonte en flux partiel — son usage
    (jamais reçu) doit être estimé. (Avec du budget, elle est rejouée : test suivant.)"""
    from bouzecode.backend.agent.providers.backends import openrouter_stream
    monkeypatch.setattr(openrouter_stream, "_STREAM_ERROR_BACKOFFS_S", ())
    result = _openai(monkeypatch, "deepseek-v4-flash", [
        _Reponse(_flux("openrouter_natif.sse"), casse_apres=2),
        _Reponse(_flux("openai_final.sse"))])
    premier = _aucun_zero(result)[0]
    assert premier.get("api_input_estimated") is True
    assert premier.get("api_output_estimated") is True


def test_openrouter_connexion_coupee_apres_du_texte_est_rejouee(monkeypatch):
    """Session 9d81964e : la coupure après production tuait le process ; elle est rejouée."""
    result = _openai(monkeypatch, "deepseek-v4-flash", [
        _Reponse(_flux("openrouter_natif.sse"), casse_apres=2),
        _Reponse(_flux("openrouter_natif.sse")), _Reponse(_flux("openai_final.sse"))])
    premier = _aucun_zero(result)[0]
    assert premier["api_output_tokens"] == 140 and not premier.get("api_output_estimated")


def test_gateway_preprod_litellm_usage_final(monkeypatch):
    result = _openai(monkeypatch, "gpt-5.5", [
        _Reponse(_flux("gateway_preprod.sse")), _Reponse(_flux("openai_final.sse"))])
    premier = _aucun_zero(result)[0]
    assert premier["api_input_tokens"] == 5200 - 4096
    assert premier["api_output_tokens"] == 310


def test_appel_annexe_sans_usage_est_estime_et_marque():
    """Les appels annexes (résumé, classifieur, rattrapage) suivent la même règle."""
    from bouzecode.backend.agent.providers.backends.dispatch import _record_side_call
    from bouzecode.backend.agent.providers.types import AssistantTurn
    from bouzecode.backend.agent.state import AgentState
    state = AgentState()
    config = {"_main_config_id": 1, "_state": state, "_call_label": "classifieur"}
    empreinte = {"longueurs": {"system": 3500, "messages": 700}}
    _record_side_call(config, "claude-opus-5", AssistantTurn("réponse " * 10, [], 0, 0), empreinte)
    entree = state.compaction_log[-1]
    assert entree["api_input_tokens"] == 1200 and entree["api_input_estimated"] is True
    assert entree["api_output_tokens"] > 0 and entree["api_output_estimated"] is True
