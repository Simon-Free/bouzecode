"""Smoke navigateur de l'onglet « Rendu » d'une tâche : affiché, rempli, enregistré, rechargé, relu.

Les routes /api/micros/<id>/rendu sont simulées avec un état Python (le stockage réel et la
validation sont couverts par tests/web_v2/test_rendu_humain.py) : ce test prouve le parcours
UI et l'absence d'erreur console.
"""
from __future__ import annotations

import json

import pytest

MICRO = "m-rendu-1"

MONTER = """async (id) => {
  const m = await import('/static/js/bureau/tache_rendu.js');
  let zone = document.getElementById('zone-test');
  if (zone) zone.remove();
  zone = document.createElement('div');
  zone.id = 'zone-test';
  document.body.prepend(zone);
  zone.appendChild(m.zoneRendu({ id }));
}"""


@pytest.mark.playwright
def test_onglet_rendu_saisi_enregistre_relu(page_with_console_errors, server):
    page, errors = page_with_console_errors
    etat: dict = {"rendu": None, "posts": []}

    def router(route, request):
        if request.method == "POST":
            corps = json.loads(request.post_data or "{}")
            etat["posts"].append(corps)
            etat["rendu"] = dict(corps, ticket_id="42", at="2026-10-14T16:00:00+00:00")
            route.fulfill(status=201, content_type="application/json",
                          body=json.dumps({"ok": True, "ticket_id": "42"}))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"rendu": etat["rendu"]}))

    page.route(f"**/api/micros/{MICRO}/rendu", router)
    page.goto(server + "/")
    page.evaluate(MONTER, MICRO)

    onglet = page.locator("#zone-test [data-rendu=onglet]")
    assert onglet.is_visible()
    onglet.locator("summary").click()
    champ = lambda nom: page.locator(f"#zone-test [data-rendu={nom}]")  # noqa: E731
    champ("auteur").fill("Alice")
    champ("symptoms").fill("Le bouton ne répond pas")
    champ("explanation").fill("Handler non branché")
    champ("tests_nombre").fill("3")
    champ("tests_niveau").fill("route")
    champ("tests_verts").check()
    champ("tests_chemin").fill("tests/web_v2/test_bouton.py")
    champ("commits").fill("abc1234 feature/bouton")
    champ("changes").fill("src/app.py | branche le handler")
    champ("taches_terminees").fill("Brancher le handler")
    champ("taches_restantes").fill("Couvrir le e2e | brief | decision")
    champ("envoyer").click()
    page.wait_for_function(
        "() => document.querySelector('#zone-test [data-rendu=statut]').textContent.includes('42')")

    envoye = etat["posts"][0]
    assert envoye["auteur"] == "Alice"
    assert envoye["recap"]["changes"] == [{"file": "src/app.py", "summary": "branche le handler"}]
    assert envoye["tests_detail"] == {"nombre": 3, "niveau": "route", "verts": True,
                                      "chemin": "tests/web_v2/test_bouton.py"}
    assert envoye["commits"] == [{"sha": "abc1234", "branche": "feature/bouton"}]
    assert envoye["taches_restantes"][0]["decision"] is True
    assert "## 6." in envoye["answer"]

    # Rechargement : la page repart de zéro et relit le rendu enregistré.
    page.reload()
    page.evaluate(MONTER, MICRO)
    page.locator("#zone-test [data-rendu=onglet] summary").click()
    page.wait_for_function(
        "() => document.querySelector('#zone-test [data-rendu=auteur]').value === 'Alice'")
    assert champ("symptoms").input_value() == "Le bouton ne répond pas"
    assert champ("commits").input_value() == "abc1234 feature/bouton"
    assert champ("tests_verts").is_checked()
    assert champ("taches_restantes").input_value() == "Couvrir le e2e | brief | decision"
    assert errors == [], errors
