# [desc] E2E thème : le clair (fond blanc) est le défaut sur chaque page, même avec l'ancienne clé « bz.theme=dark » ; ◐ passe au sombre, le mémorise, et revient au clair. [/desc]
from __future__ import annotations

import pytest

from agents_e2e_support import BASE, MARQUES, browser, expect, pg  # noqa: F401 — fixtures importées

pytestmark = [*MARQUES, pytest.mark.couvre("static/ds.css", "static/js/chrome.js", "templates/base.html")]

BLANC = "rgb(255, 255, 255)"


def fond(page) -> str:
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


@pytest.mark.parametrize("chemin", ["/bureau", "/conversations", "/agent-builder"])
def test_le_clair_est_le_defaut_meme_avec_l_ancienne_cle(pg, chemin):
    """Mode jour demandé : fond blanc sans aucun choix, et l'ancienne clé écrite d'office n'impose plus le sombre."""
    page = pg.page
    page.add_init_script("localStorage.setItem('bz.theme', 'dark')")
    page.goto(f"{BASE}{chemin}")
    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")
    assert fond(page) == BLANC
    assert page.evaluate("localStorage.getItem('bz.theme.choix')") is None
    assert pg.erreurs_inattendues() == []


def test_le_bouton_bascule_au_sombre_le_memorise_et_revient(pg):
    page = pg.page
    page.goto(f"{BASE}/conversations")
    bouton = page.locator("#theme-toggle")
    bouton.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(bouton).to_have_attribute("aria-pressed", "true")
    assert fond(page) != BLANC
    page.goto(f"{BASE}/bureau")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator("#theme-toggle").click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")
    page.reload()
    assert fond(page) == BLANC
    assert pg.erreurs_inattendues() == []
