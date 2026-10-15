# [desc] Xiaomi MiMo V2.6 Pro par OpenRouter : payload (slug, fournisseur épinglé, raisonnement), tool_calls natifs rejoués depuis de vraies réponses capturées, coût aux tarifs publiés. [/desc]
"""MiMo V2.6 Pro (`mimo-v2.6-pro` → `xiaomi/mimo-v2.6-pro`), mesuré le 24/09.

Les fichiers de `mimo_sse/` sont des réponses SSE RÉELLES, copiées telles quelles :
- `appels_paralleles.sse` : sonde directe sur xiaomi/fp8, un lot Methodology + 2 Read en
  parallèle, précédé de raisonnement (`delta.reasoning`, envoyé par défaut par MiMo) ;
- `arguments_vides.sse` : un tour de l'essai headless où MiMo a émis Methodology et
  Environment avec `arguments: "{}"` (6 appels sur 38 dans l'essai) ;
- `usage_cache.sse` : dernier chunk d'un 2e appel au même préfixe, 6 784 tokens lus en cache,
  avec le `cost` facturé par OpenRouter.
Seule la session HTTP est remplacée ; tout le reste passe par `dispatch.stream`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bouzecode.backend.agent.providers.backends import dispatch, openrouter_provider, openrouter_stream
from bouzecode.backend.agent.providers.registry import calc_cost, resolve_provider
from bouzecode.backend.agent.providers.types import AssistantTurn, ThinkingChunk, ToolCallParsed
from bouzecode.backend.core.config import DEFAULTS

SSE = Path(__file__).parent / "mimo_sse"


class _Reponse:
    status_code, ok, encoding, text = 200, True, "utf-8", ""

    def __init__(self, lignes: list[str]) -> None:
        self.lignes = lignes

    def iter_lines(self, decode_unicode=False):
        return iter(self.lignes)


class _FauxOpenRouter:
    """Rejoue un fichier SSE capturé et garde les payloads reçus."""
    def __init__(self, fichier: str) -> None:
        self.lignes = (SSE / fichier).read_text(encoding="utf-8").splitlines()
        self.payloads: list[dict] = []

    def post(self, url, **kw):
        self.payloads.append(json.loads(json.dumps(kw["json"])))
        return _Reponse(self.lignes)


@pytest.fixture
def rejouer(monkeypatch):
    monkeypatch.setattr(openrouter_provider, "_courant", {})
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")

    def _rejouer(fichier: str, **reglages) -> tuple[_FauxOpenRouter, list]:
        serveur = _FauxOpenRouter(fichier)
        monkeypatch.setattr(openrouter_stream, "_build_session", lambda: serveur)
        config = {**DEFAULTS, "model": "mimo-v2.6-pro", **reglages}
        evenements = list(dispatch.stream("mimo-v2.6-pro", "Tu es un agent.",
                                          [{"role": "user", "content": "Lis a.py et b.py."}], [], config))
        return serveur, evenements

    return _rejouer


def _tour(evenements: list) -> AssistantTurn:
    return next(e for e in evenements if isinstance(e, AssistantTurn))


def test_nom_court_resolu_vers_le_slug_openrouter():
    assert resolve_provider("mimo-v2.6-pro") == ("openrouter", "xiaomi/mimo-v2.6-pro")


def test_payload_slug_fournisseur_epingle_et_raisonnement_par_defaut(rejouer):
    serveur, _ = rejouer("appels_paralleles.sse")

    payload = serveur.payloads[0]
    assert payload["model"] == "xiaomi/mimo-v2.6-pro"
    assert payload["provider"] == {"order": ["xiaomi/fp8"], "allow_fallbacks": False,
                                   "require_parameters": True}, "xiaomi/fp8 : le seul qui cache dès le 2e appel"
    assert "reasoning" not in payload, "MiMo raisonne par défaut (court) : aucun réglage envoyé"
    assert payload["tool_choice"] == "auto"


def test_repli_configure_sur_deepinfra():
    assert DEFAULTS["openrouter_provider"]["mimo-v2.6-pro"] == ["xiaomi/fp8", "deepinfra/fp8"]


def test_raisonnement_natif_demande_explicitement(rejouer):
    serveur, _ = rejouer("appels_paralleles.sse", native_reasoning=True)

    assert serveur.payloads[0]["reasoning"] == {"enabled": True}


def test_appels_paralleles_captures_sont_parses(rejouer):
    _, evenements = rejouer("appels_paralleles.sse")

    appels = [(e.name, e.inputs, e.tool_id) for e in evenements if isinstance(e, ToolCallParsed)]
    assert [(nom, entree.get("file_path")) for nom, entree, _ in appels] == [
        ("Methodology", None), ("Read", "a.py"), ("Read", "b.py")]
    assert appels[0][1]["note"].startswith("Lecture parallèle")
    assert [i for _, _, i in appels] == ["call_cddc78b151f34a9ca1448032", "call_f96a3b42dd2840749aae5c17",
                                         "call_0755f33de0e44ecabc64264b"]
    assert any(isinstance(e, ThinkingChunk) for e in evenements), "le raisonnement arrive en ThinkingChunk"
    tour = _tour(evenements)
    assert (tour.stop_reason, tour.provider, tour.in_tokens, tour.out_tokens) == ("tool_calls", "Xiaomi", 224, 101)


def test_arguments_vides_refuses_sans_tuer_l_agent(rejouer):
    """MiMo émet parfois `{}` pour un lot entier. Le harnais doit rendre l'erreur au modèle
    (qui ré-émet au tour suivant) ; un `inputs["command"]` direct tuait le process (KeyError)."""
    from bouzecode.backend.tools.registration import execute_tool

    _, evenements = rejouer("arguments_vides.sse")

    appels = _tour(evenements).tool_calls
    assert [(a["name"], a["input"]) for a in appels] == [("Methodology", {}), ("Environment", {})]
    for nom in ("Methodology", "Environment", "Bash", "Write", "Edit"):
        erreur = execute_tool(nom, {}, "accept-all", config={"model": "mimo-v2.6-pro"})
        assert erreur.startswith(f"Error: required parameter(s) for {nom} arrived empty or missing")
        assert "as plain JSON string values" in erreur, "en natif, pas de conseil « mets du CDATA »"
        assert "Wrap values" not in erreur


def test_cout_egal_a_celui_facture_par_openrouter(rejouer):
    serveur, evenements = rejouer("usage_cache.sse")
    facture = json.loads(serveur.lignes[0][len("data: "):])["usage"]["cost"]

    tour = _tour(evenements)
    assert (tour.in_tokens, tour.cache_read_tokens, tour.out_tokens) == (113, 6784, 232)
    cout = calc_cost("mimo-v2.6-pro", tour.in_tokens, tour.out_tokens, tour.cache_read_tokens,
                     tour.cache_creation_tokens)
    assert cout == pytest.approx(facture, rel=1e-6)


def test_tarifs_publies_par_million():
    assert calc_cost("mimo-v2.6-pro", 1_000_000, 0) == pytest.approx(0.435)
    assert calc_cost("mimo-v2.6-pro", 0, 1_000_000) == pytest.approx(0.87)
    assert calc_cost("mimo-v2.6-pro", 0, 0, cache_read_tok=1_000_000) == pytest.approx(0.0036)
