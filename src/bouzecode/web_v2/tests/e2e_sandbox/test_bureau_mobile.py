# [desc] Bureau sur téléphone (390 px, tactile) : pas une colonne de boutons « Lancer » sur chaque ligne repliée, titres lisibles (deux lignes plutôt qu'une douzaine de caractères), bulle de l'assistant qui ne masque aucune commande en bas de page. [/desc]
"""Mise en page mesurée dans un vrai navigateur mobile contre le bac à sable."""
from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    BASE, DEPOT, MARQUES, bz_browser, creer_tache, ouvrir_bureau, section_statut, tache_loc, uid,
)

SCAN = (Path(__file__).parent / "contraste_scan.js").read_text(encoding="utf-8")

pytestmark = [*MARQUES, pytest.mark.couvre("static/css/bureau.css", "templates/bureau.html", "static/ds.css")]


@pytest.fixture()
def mobile(bz_browser):
    ctx = bz_browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    yield page
    ctx.close()


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


def _chevauche(a, b) -> bool:
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])


def test_bureau_sur_telephone(mobile):
    titre = f"Documenter le module d'export des factures {uid('m')}"
    t = creer_tache(titre, "Brief", projet_slug=DEPOT)
    ouvrir_bureau(mobile)
    ligne = tache_loc(mobile, t["id"])
    ligne.scroll_into_view_if_needed()
    assert mobile.evaluate(PLACEHOLDERS_COUPES) == [], "textes d'aide coupés dans leur champ"
    # Au doigt, la poignée ⠿ est toujours affichée : elle doit rester lisible (WCAG 4.5:1).
    assert mobile.evaluate(SCAN, {"racine": "#lignes-liste", "seuil": 4.5}) == []
    # Lignes repliées : aucune action posée à droite de chaque titre (elle vit dans le détail).
    actions = section_statut(mobile, "a_lancer").locator(".bz-task:not(.is-open) > .bz-task__row .bz-task__action")
    assert actions.count() > 0
    visibles = [i for i in range(actions.count()) if actions.nth(i).is_visible()]
    assert visibles == [], f"{len(visibles)} boutons d'action visibles sur des lignes repliées"
    # Titre lisible : entier, sur deux lignes au plus.
    el = ligne.locator(".bz-task__titre")
    largeur, visible, hauteur, interligne = el.evaluate(
        "e => [e.scrollWidth, e.clientWidth, e.getBoundingClientRect().height, parseFloat(getComputedStyle(e).lineHeight)]")
    assert largeur <= visible + 1, "titre coupé en largeur"
    assert hauteur <= 2 * interligne + 2, f"titre sur plus de deux lignes ({hauteur} px)"
    # Déplier donne le geste.
    el.click()
    expect(ligne.get_by_role("button", name="Lancer").first).to_be_visible()
    # En bas de page, la bulle de l'assistant ne recouvre aucune commande.
    mobile.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    mobile.wait_for_timeout(300)
    fab = mobile.locator("#assistant-bulle").bounding_box()
    commandes = mobile.locator(".bz-page button:visible, .bz-page select:visible, .bz-page textarea:visible, .bz-page input:visible")
    for i in range(commandes.count()):
        b = commandes.nth(i).bounding_box()
        if b and b["y"] < 844 and b["y"] + b["height"] > 0:
            assert not _chevauche(fab, b), f"la bulle masque {commandes.nth(i).evaluate('e => e.outerHTML.slice(0, 120)')}"
