# [desc] Fournisseur OpenRouter épinglé : échec → reprises sur le même fournisseur → repli sur l'ordre complet → la session reste sur le fournisseur de repli ; changements journalisés ; réglage désactivable. [/desc]
"""Épinglage du fournisseur OpenRouter (docs/reduction_tokens/correctifs.md, point « fournisseur »).

Chaque fournisseur a son propre cache : le routage libre d'OpenRouter faisait rater le cache
(26 % du non-caché dans le rapport). On joue de vraies requêtes par `dispatch.stream` ; seule
la session HTTP est remplacée par un faux OpenRouter qui répond selon le champ `provider`.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.backend.agent.providers.backends import dispatch, openrouter_provider, openrouter_stream
from bouzecode.backend.agent.providers.types import AssistantTurn
from bouzecode.backend.agent.state import AgentState

ORDRE = ["deepinfra/fp8", "wafer", "streamlake/fp8"]


class _Reponse:
    encoding, text = "utf-8", "rate limited"

    def __init__(self, statut: int, servi: str = "") -> None:
        self.status_code, self.ok, self.servi = statut, statut == 200, servi

    def iter_lines(self, decode_unicode=False):
        chunk = {"provider": self.servi, "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 1}}
        yield "data: " + json.dumps(chunk)
        yield "data: [DONE]"


class _FauxOpenRouter:
    """DeepInfra sature (429) ; en repli, OpenRouter sert Wafer."""
    def __init__(self) -> None:
        self.providers: list[dict] = []

    def post(self, url, **kw):
        provider = kw["json"].get("provider")
        self.providers.append(provider)
        if provider and provider["order"][0] == "deepinfra/fp8" and not provider["allow_fallbacks"]:
            return _Reponse(429)
        return _Reponse(200, "Wafer")


@pytest.fixture
def faux(monkeypatch):
    serveur, pauses = _FauxOpenRouter(), []
    monkeypatch.setattr(openrouter_stream, "_build_session", lambda: serveur)
    monkeypatch.setattr(openrouter_stream, "_sleep", pauses.append)
    monkeypatch.setattr(openrouter_provider, "_courant", {})
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    return serveur, pauses


def _appel(config: dict) -> AssistantTurn:
    evenements = list(dispatch.stream(config["model"], "Tu es un agent.",
                                      [{"role": "user", "content": "salut"}], [], config))
    return next(e for e in evenements if isinstance(e, AssistantTurn))


def test_echec_reprises_meme_fournisseur_puis_repli_puis_collage(faux):
    serveur, pauses = faux
    state = AgentState()
    config = {"model": "deepseek-v4.1-flash", "openrouter_provider": {"deepseek-v4.1-flash": ORDRE},
              "_state": state}

    tour1 = _appel(config)

    epingle = {"order": ["deepinfra/fp8"], "allow_fallbacks": False, "require_parameters": True}
    assert serveur.providers[:4] == [epingle] * 4, "1 essai + 3 reprises sur le MÊME fournisseur"
    assert pauses == [1.0, 2.0, 3.0], "reprises courtes (≈ 6 s) avant le repli"
    assert serveur.providers[4] == {"order": ORDRE, "allow_fallbacks": True, "require_parameters": True}
    assert tour1.provider == "Wafer"

    _appel(config)

    assert serveur.providers[5] == {"order": ["wafer"], "allow_fallbacks": False,
                                    "require_parameters": True}, "la session reste sur le repli"
    changements = [e for e in state.compaction_log if e["event"] == "provider_switch"]
    assert [(e["from"], e["to"].split(",")[0]) for e in changements] == [
        ("deepinfra/fp8", "repli sur deepinfra/fp8"), ("deepinfra/fp8", "wafer")]


def test_reglage_vide_routage_libre(faux):
    serveur, _ = faux

    _appel({"model": "deepseek-v4.1-flash", "openrouter_provider": {}})

    assert serveur.providers == [None], "aucun champ provider : routage libre d'OpenRouter"


def test_defaut_de_la_config_pour_deepseek_v41_flash():
    from bouzecode.backend.core.config import DEFAULTS

    assert DEFAULTS["openrouter_provider"]["deepseek-v4.1-flash"] == ORDRE


def test_enquete_signale_le_changement_de_fournisseur():
    from bouzecode.web_v2.services.sessions.enquete import marqueurs

    avant = {"turn": 1, "api_input_tokens": 100, "api_cache_read": 900, "provider": "DeepInfra"}
    apres = {"turn": 2, "api_input_tokens": 1000, "api_cache_read": 0, "provider": "Wafer"}

    assert "changement_fournisseur" in marqueurs.marqueurs(apres, avant, None, None, None)
    assert "changement_fournisseur" not in marqueurs.marqueurs({**apres, "provider": "DeepInfra"},
                                                               avant, None, None, None)


def test_repli_servi_hors_liste_pas_de_collage(faux, monkeypatch):
    """En repli (`allow_fallbacks: true`), OpenRouter peut servir par un fournisseur hors de
    l'ordre configuré (ex. morph, exclu) : la session ne s'y colle pas."""
    serveur, _ = faux
    monkeypatch.setattr(_FauxOpenRouter, "post", lambda self, url, **kw: (
        self.providers.append(kw["json"].get("provider"))
        or (_Reponse(429) if not kw["json"]["provider"]["allow_fallbacks"] else _Reponse(200, "Morph"))))
    config = {"model": "deepseek-v4.1-flash", "openrouter_provider": {"deepseek-v4.1-flash": ORDRE}}

    assert _appel(config).provider == "Morph"

    assert openrouter_provider._courant == {}, "pas de collage à un fournisseur hors liste"
    _appel(config)
    assert serveur.providers[5]["order"] == ["deepinfra/fp8"]
