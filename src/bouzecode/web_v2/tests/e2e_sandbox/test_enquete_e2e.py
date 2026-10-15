"""Vue d'enquête sur un vrai agent du bac à sable (faux LLM, scénario `tools`) : lien depuis
« Coûts & tours », frise, tour avec rupture du préfixe, navigation clavier, note, saturation,
recherche, erreur de chargement visible."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from agents_e2e_support import (  # noqa: F401 — fixtures importées
    BASE, MARQUES, Retenue, api, attendre_etat, browser, cle_agent, lancer, ouvrir_agent, pg, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "routes/enquete.py", "services/sessions/enquete/**", "runtime/context_viewer/**",
    "templates/enquete.html", "static/js/enquete/**", "static/css/enquete.css",
    "static/js/conversations/panel/costs.js", "templates/base.html", "static/js/lib/**",
    "static/js/chrome.js", "static/ds.css")]


@pytest.fixture(scope="module")
def agent():
    """Un agent terminé qui a appelé plusieurs outils sur plusieurs tours."""
    key = cle_agent(lancer(uid("enquete"), "tools"))
    attendre_etat(key, {"finished", "idle"}, delai=120)
    return key.split("/", 1)[1]


def test_depuis_couts_et_tours_on_ouvre_l_enquete_d_un_tour(pg, agent):
    ouvrir_agent(pg, f"agent/{agent}")
    pg.page.get_by_role("tab", name="Coûts & tours").click()
    lien = pg.page.locator(".ag-enquete-lien", has_text="Enquêter").first
    lien.wait_for()
    href = lien.get_attribute("href")
    assert href.startswith(f"/enquete/{agent}#tour-")
    pg.page.goto(f"{BASE}{href}")
    pg.page.locator(".eq-el").first.wait_for()
    assert pg.page.locator(".eq-ligne[aria-current='true']").count() == 1


def test_la_frise_se_charge_avec_un_squelette_puis_le_tour_explique_le_cache(pg, agent):
    retenue = Retenue(pg.page, "**/api/enquete/*/frise")
    pg.page.goto(f"{BASE}/enquete/{agent}#tour-2")
    pg.page.locator("#eq-liste .skeleton").wait_for()          # indicateur pendant l'attente
    retenue.relacher()
    pg.page.locator(".eq-rupture").wait_for()
    assert "préfixe" in pg.page.locator(".eq-rupture").inner_text()
    assert pg.page.locator(".eq-api__case").count() == 4
    #  k part aussitôt après que l'URL est passée à #tour-3, SANS attendre le hashchange : c'est
    #  ce que fait un utilisateur rapide (ou une touche maintenue), la vue doit le suivre.
    pg.page.keyboard.press("j")
    pg.page.wait_for_url("**#tour-3")
    pg.page.keyboard.press("k")
    pg.page.wait_for_url("**#tour-2")
    expect(pg.page.locator("#eq-tour h2")).to_have_text("Tour 2")


def test_note_saturation_et_recherche(pg, agent):
    pg.page.goto(f"{BASE}/enquete/{agent}#note")
    pg.page.locator("#vue-note .eq-graphe").wait_for()
    assert pg.page.locator(".eq-note").count() >= 1
    pg.page.goto(f"{BASE}/enquete/{agent}#saturation")
    pg.page.locator("#vue-saturation .eq-table tbody tr").first.wait_for()
    pg.page.locator("#eq-q").fill("Methodology")
    pg.page.locator("#eq-q").press("Enter")
    pg.page.locator(".eq-res").first.wait_for()
    pg.page.locator(".eq-res a[href^='#tour-']").first.click()
    pg.page.locator(".eq-el").first.wait_for()


def test_une_erreur_de_chargement_d_un_tour_se_voit_et_se_reessaie(pg, agent):
    pg.autoriser("500")
    pg.page.route("**/api/enquete/*/tours/1", lambda r: r.fulfill(status=500, body='{"error":"panne simulée"}',
                                                                  content_type="application/json"))
    pg.page.goto(f"{BASE}/enquete/{agent}#tour-1")
    erreur = pg.page.locator("#eq-tour .error-state")
    erreur.wait_for()
    assert "panne simulée" in erreur.inner_text()
    pg.page.unroute("**/api/enquete/*/tours/1")
    erreur.get_by_role("button").click()
    pg.page.locator(".eq-el").first.wait_for()


def test_agent_sans_donnees(pg):
    pg.autoriser("404")
    pg.page.goto(f"{BASE}/enquete/inconnu000000")
    pg.page.locator("#eq-tour .error-state").wait_for()
    assert api("GET", "/api/enquete/inconnu000000/frise").get("error")
