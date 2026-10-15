# [desc] BOUZECODE_ALLOWED_PROVIDERS refuse un fournisseur hors liste (openrouter) avant toute clé ou requête ; absente, aucun filtre. [/desc]
"""Un process hébergé (Demo) doit pouvoir interdire qu'un modèle choisi parte chez
OpenRouter : le contexte quitterait le gateway IA."""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers import registry
from bouzecode.backend.agent.providers.backends import dispatch


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(registry.ALLOWED_PROVIDERS_ENV, raising=False)


def test_sans_liste_blanche_aucun_filtre():
    registry.check_provider_allowed("openrouter", "deepseek-v4-flash")


def test_openrouter_refuse_avant_toute_cle_ni_requete(monkeypatch):
    monkeypatch.setenv(registry.ALLOWED_PROVIDERS_ENV, "anthropic, gateway_openai")

    def jamais(*a, **k):
        raise AssertionError("aucune clé ne doit être lue pour un fournisseur refusé")

    monkeypatch.setattr(dispatch, "_require_key", jamais)
    with pytest.raises(registry.ProviderNotAllowed) as info:
        next(dispatch.stream("deepseek-v4-flash", "", [], [], {}))
    assert "openrouter" in str(info.value) and registry.ALLOWED_PROVIDERS_ENV in str(info.value)


def test_fournisseur_autorise_passe(monkeypatch):
    monkeypatch.setenv(registry.ALLOWED_PROVIDERS_ENV, "anthropic")
    registry.check_provider_allowed(registry.resolve_provider("claude-sonnet-4-5")[0])
