# [desc] Page Agents sur téléphone (390 px) : aucun débordement horizontal même avec plusieurs onglets, fil de hauteur bornée qui défile seul et suit la fin, champ de message visible sans faire défiler la page. [/desc]
"""Mise en page mesurée dans un vrai navigateur mobile (viewport 390 × 844, tactile) contre le bac
à sable : ce que seuls des pixels prouvent."""
from __future__ import annotations

import pytest

from agents_e2e_support import (  # noqa: F401 — fixtures importées
    BASE, MARQUES, attendre_etat, browser, cle_agent, expect, lancer, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre("static/css/agents.css", "static/js/conversations/tabs.js",
                                           "templates/conversations.html", "static/ds.css")]

PLACEHOLDERS_COUPES = """() => {
  const ctx = document.createElement("canvas").getContext("2d");
  const out = [];
  for (const el of document.querySelectorAll("textarea[placeholder], input[placeholder]")) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.value) continue;
    const cs = getComputedStyle(el);
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const dispo = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const lignes = el.tagName === "TEXTAREA"
      ? Math.max(1, Math.round((el.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)) / (parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3)))
      : 1;
    const largeur = ctx.measureText(el.placeholder).width;
    //  Marge pour les coupures de mots en fin de ligne d'un textarea.
    if (largeur > dispo * lignes * (lignes > 1 ? 0.85 : 1)) out.push(`${el.getAttribute("aria-label") || el.id}: « ${el.placeholder} »`);
  }
  return out;
}"""


LARGEUR, HAUTEUR = 390, 844


@pytest.fixture()
def mobile(browser):
    ctx = browser.new_context(viewport={"width": LARGEUR, "height": HAUTEUR}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    erreurs = []
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    yield page
    ctx.close()
    assert not erreurs, erreurs


def test_page_agents_sur_telephone_onglets_fil_et_champ(mobile):
    titres = [uid("Mobile") for _ in range(4)]
    cles = [cle_agent(lancer(t, "long")) for t in titres]
    for k in cles:
        attendre_etat(k, {"finished", "idle"}, 90)
    mobile.goto(f"{BASE}/conversations", wait_until="domcontentloaded")
    expect(mobile.locator(".ag-card").first).to_be_visible(timeout=20000)
    assert mobile.evaluate(PLACEHOLDERS_COUPES) == [], "textes d'aide coupés dans leur champ"
    for t in titres:
        mobile.locator(".ag-card").filter(has_text=t).first.click()
        expect(mobile.locator(".ag-panel:not([hidden]) .ag-head__title")).to_have_text(t)
    largeur = mobile.evaluate("document.documentElement.scrollWidth")
    assert largeur <= LARGEUR, f"débordement horizontal : la page fait {largeur} px de large"
    panneau = mobile.locator(".ag-panel:not([hidden])")
    expect(panneau.locator(".block.assistant").first).to_be_visible(timeout=20000)
    mobile.wait_for_timeout(800)
    fil = panneau.locator(".ag-thread")
    boite = fil.bounding_box()
    assert boite["height"] < HAUTEUR, f"fil sans hauteur bornée ({boite['height']} px)"
    haut, total, visible = fil.evaluate("e => [e.scrollTop, e.scrollHeight, e.clientHeight]")
    assert total > visible, "conversation longue : le fil doit défiler en lui-même"
    assert haut + visible >= total - 60, "le fil suit la fin de la conversation"
    champ = panneau.locator(".ag-composer__input").bounding_box()
    assert 0 <= champ["y"] and champ["y"] + champ["height"] <= HAUTEUR, \
        f"champ de message hors de l'écran (y={champ['y']})"
