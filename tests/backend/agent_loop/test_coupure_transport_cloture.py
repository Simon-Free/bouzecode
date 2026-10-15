# [desc] Coupure de transport en vol, relances épuisées : la session se clôt avec close_reason='api_error' et sa cause, sans exception qui tue le process. [/desc]
"""Session 9d81964e (2026-10-06) : `ChunkedEncodingError` au 69e tour → traceback, process
tué, close_reason vide, travail non intégré."""
from __future__ import annotations

import requests

from bouzecode.backend.agent.loop import coupure_de_transport
from tests.backend.providers.test_usage_flux_enregistres_e2e import _Reponse, _flux, _openai


def test_coupure_apres_reflexion_relances_epuisees_clot_proprement(monkeypatch):
    from bouzecode.backend.agent.providers.backends import openrouter_stream
    monkeypatch.setattr(openrouter_stream, "_STREAM_ERROR_BACKOFFS_S", ())
    #  Le cas réel : seule la RÉFLEXION est partie (aucun texte, aucun appel d'outil) —
    #  loop_turn ne peut pas en faire un tour partiel, l'exception remontait.
    reflexion = ('data: {"choices": [{"index": 0, "delta": {"reasoning": "je réfléchis"}}]}'
                 + "\n\n" + _flux("openrouter_natif.sse"))
    result = _openai(monkeypatch, "deepseek-v4-flash", [_Reponse(reflexion, casse_apres=2)],
                     native_reasoning=True)
    assert result.state.close_reason == "api_error"
    assert "ChunkedEncodingError" in result.state.close_detail


def test_reconnait_les_coupures_de_transport_et_rien_d_autre():
    assert coupure_de_transport(requests.exceptions.ChunkedEncodingError("x"))
    assert coupure_de_transport(requests.exceptions.ReadTimeout("x"))
    assert not coupure_de_transport(ValueError("x"))
