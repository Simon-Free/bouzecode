"""Smoke navigateur de la section « Fichiers livrés » d'un récap : listée, état, bouton Ouvrir.

La route POST /api/fichiers/ouvrir est simulée (sa sécurité est couverte par
tests/web_v2/test_related_files.py) : ce test prouve l'affichage et l'appel envoyé."""
from __future__ import annotations

import json

import pytest

MONTER = """async (files) => {
  const m = await import('/static/js/lib/fichiers_livres.js');
  let zone = document.getElementById('zone-test');
  if (zone) zone.remove();
  zone = document.createElement('div');
  zone.id = 'zone-test';
  document.body.prepend(zone);
  zone.appendChild(m.fichiersLivres(files, { micro_id: 'm-1' }));
}"""

FICHIERS = [
    {"path": "C:/livrables/rapport.html", "label": "Rapport", "kind": "html",
     "name": "rapport.html", "exists": True},
    {"path": "C:/livrables/deck.pptx", "name": "deck.pptx", "exists": False},
]


@pytest.mark.playwright
def test_section_fichiers_livres_et_bouton_ouvrir(page_with_console_errors, server):
    page, errors = page_with_console_errors
    posts: list = []

    def router(route, request):
        posts.append(json.loads(request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    page.route("**/api/fichiers/ouvrir", router)
    page.goto(server + "/")
    page.evaluate(MONTER, FICHIERS)

    section = page.locator("#zone-test [data-fichiers=section]")
    assert section.is_visible()
    assert "Fichiers livrés" in section.inner_text()
    items = page.locator("#zone-test [data-fichiers=item]")
    assert items.count() == 2
    assert "rapport.html" in items.nth(0).inner_text()
    assert "C:/livrables/deck.pptx" in items.nth(1).inner_text()
    boutons = page.locator("#zone-test [data-fichiers=ouvrir]")
    assert boutons.count() >= 1
    boutons.first.click()
    page.wait_for_function("() => true")
    page.wait_for_timeout(300)
    assert posts and posts[0]["path"] == "C:/livrables/rapport.html", posts
    assert posts[0]["micro_id"] == "m-1"
    assert errors == [], errors
