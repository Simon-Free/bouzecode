# [desc] Installer un agent depuis le catalogue le fait basculer dans la liste des installés, sans rechargement. [/desc]
"""Catalogue d'agents : le parcours d'installation, cliqué pour de vrai.

POURQUOI UN NAVIGATEUR EST INDISPENSABLE ICI : ce test ne porte pas sur l'API — le
contrat HTTP (`/api/agents/catalog`, `/api/agents/install`, `/api/agents/catalog/refresh`)
est déjà prouvé au client de test Flask dans `tests/test_agent_catalog_api.py`, sans
navigateur. Ce qui reste à prouver est le CÂBLAGE de la page : le bouton « Installer »
est bien rendu sur la bonne ligne, le clic déclenche l'appel, et la liste se redessine
toute seule pour montrer l'agent du bon côté. C'est du JavaScript exécuté sur un vrai
clic : aucune réponse HTTP ne le montre.

Le catalogue est remplacé, dans ce processus, par deux profils déterministes (un
installé, un disponible) pour que le parcours ne dépende pas du poste.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bouzecode.backend.multi_agent import plugin_resolver
from bouzecode.backend.profiles import catalog
from bouzecode.web_v2.services import agent_catalog as svc


def _profile(name: str, requires: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} summary",
        tools=["Read", "Write"],
        skills=[],
        hooks=[],
        model="",
        system_prompt_extra="",
        requires_plugins=list(requires),
    )


_CATALOG = {
    "installed-agent": _profile("installed-agent", []),
    "available-agent": _profile("available-agent", ["nonexistent-pkg-e2e"]),
}


@pytest.fixture()
def seeded_catalog(monkeypatch):
    """Catalogue déterministe : 1 agent déjà installé, 1 agent installable."""
    installed_names = {"installed-agent"}

    def _installed_and_available():
        installed = {n: p for n, p in _CATALOG.items() if n in installed_names}
        available = {n: p for n, p in _CATALOG.items() if n not in installed_names}
        return installed, available

    def _save_profile(data):
        # Écrire le YAML revient, pour la page, à faire passer l'agent côté installés.
        installed_names.add(data.get("name"))
        return None  # une str signalerait une erreur au service

    monkeypatch.setattr(catalog, "installed_and_available", _installed_and_available)
    monkeypatch.setattr(catalog, "list_catalog_profiles", lambda: dict(_CATALOG))
    monkeypatch.setattr(catalog, "refresh_catalog", lambda force=False: None)
    monkeypatch.setattr(plugin_resolver, "ensure_plugins", lambda reqs: ([], []))
    monkeypatch.setattr(svc.profiles_svc, "save_profile", _save_profile)
    return installed_names


def _section_text(page, section_id: str) -> str:
    return page.locator(f"#{section_id}").inner_text()


def test_clicking_install_moves_the_agent_to_the_installed_list(seeded_catalog, server, page):
    """Cliquer « Installer » sur un agent disponible le fait passer, sans rechargement de
    page, dans la liste des agents installés."""
    page.goto(f"{server}/agent-builder", wait_until="domcontentloaded")
    # Le catalogue vit dans son propre onglet, hors du parcours de création.
    page.locator('#ab-tabs .tab[data-panel="ab-panel-catalog"]').click()

    # Les deux sections se remplissent depuis le catalogue.
    page.wait_for_function(
        "document.querySelector('#cat-installed') && "
        "!document.querySelector('#cat-installed').textContent.includes('Chargement')"
    )
    assert "installed-agent" in _section_text(page, "cat-installed")
    page.locator("#cat-available").wait_for()
    assert "available-agent" in _section_text(page, "cat-available")

    # Seul l'agent non installé propose un bouton d'installation.
    install_button = page.locator(
        "#cat-available .cat-row", has_text="available-agent"
    ).get_by_role("button", name="Installer")
    assert install_button.count() == 1

    install_button.click()

    page.wait_for_function(
        "document.querySelector('#cat-installed').textContent.includes('available-agent')"
    )
    assert "available-agent" in _section_text(page, "cat-installed")
    assert "available-agent" not in _section_text(page, "cat-available")

    # Rafraîchir redessine la liste sans la vider.
    page.locator("#cat-refresh").click()
    page.wait_for_function(
        "document.querySelector('#cat-installed').textContent.includes('installed-agent')"
    )
    assert "installed-agent" in _section_text(page, "cat-installed")
