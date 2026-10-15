# [desc] Playwright tests for UI gesture parity: rollback of integrated passages and posting alert reports from the task menu. [/desc]
from __future__ import annotations

import json

# Passage tel que le rend taches_vue.passage (clés de signaturePassages) : intégré.
PASSAGE_INTEGRE = {"ticket_id": "t42", "slug": "demo", "agent_id": "", "etat": "integrated", "activite": "",
                   "recap": None, "integre": True, "integrable": True, "fichiers_modifies": 1,
                   "raison_echec": "", "retour": None, "finished_at": "2026-10-14T10:00:00", "distant": False,
                   "branche": "agent/t42"}

_PASSAGES = """async (p) => {
  const m = await import('/static/js/bureau/passages.js');
  const box = document.createElement('div');
  box.id = 'zone-test';
  m.rendrePassages({ id: 'm1', passages: [p] }).forEach((n) => box.appendChild(n));
  document.body.appendChild(box);
  return [...box.querySelectorAll('button, a')].map((b) => b.textContent.trim());
}"""

_GESTES = """async (p) => {
  const m = await import('/static/js/bureau/tache_gestes.js');
  const corps = document.createElement('div');
  corps.id = 'zone-test';
  const zoneActions = document.createElement('div');
  corps.appendChild(zoneActions);
  document.body.appendChild(corps);
  const rec = { t: { id: 'm1', projet_slug: 'demo', statut_ui: '__aucun__', passages: [p] }, corps, zoneActions };
  m.gestes(rec, '').forEach((n) => zoneActions.appendChild(n));
  return true;
}"""


def _page(browser, server):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{server}/", wait_until="domcontentloaded")
    return page, errors


def _capture(page, motif, appels, corps):
    def _route(route):
        appels.append((route.request.method, route.request.url, route.request.post_data_json))
        route.fulfill(status=201, content_type="application/json", body=json.dumps(corps))
    page.route(motif, _route)


def test_rollback_poste_sur_revert(browser, server):
    page, errors = _page(browser, server)
    appels = []
    _capture(page, "**/api/micros/*/passages/*/revert", appels, {"ok": True, "deja": False, "micro": {"id": "m2"}})
    try:
        libelles = page.evaluate(_PASSAGES, PASSAGE_INTEGRE)
        assert "Demander un rollback" in libelles
        assert "Intégrer" not in libelles
        page.locator("#zone-test button", has_text="Demander un rollback").click()
        page.wait_for_timeout(500)
        assert appels and appels[0][0] == "POST"
        assert "/api/micros/m1/passages/t42/revert" in appels[0][1]
        assert not errors
    finally:
        page.close()


def test_pas_de_rollback_sur_passage_non_integre(browser, server):
    page, errors = _page(browser, server)
    try:
        libelles = page.evaluate(_PASSAGES, {**PASSAGE_INTEGRE, "integre": False})
        assert "Demander un rollback" not in libelles
        assert "Intégrer" in libelles
        assert not errors
    finally:
        page.close()


def test_menu_signaler_poste_un_signalement(browser, server):
    page, errors = _page(browser, server)
    appels = []
    _capture(page, "**/api/signalements", appels, {"ok": True, "signalement": {"id": "s1"}})
    try:
        page.evaluate(_GESTES, PASSAGE_INTEGRE)
        page.locator("#zone-test button[aria-label='Autres actions sur la tâche']").click()
        page.locator(".menu__item", has_text="Signaler une alerte…").click()
        page.locator("#zone-test textarea[aria-label='Signalement']").fill("Base cassée\nle build échoue")
        page.locator("#zone-test .bz-consigne button", has_text="Signaler").click()
        page.wait_for_timeout(500)
        assert appels and appels[0][0] == "POST"
        corps = appels[0][2]
        assert corps["gravite"] == "alerte"
        assert corps["titre"] == "Base cassée"
        assert corps["detail"] == "le build échoue"
        assert corps["ticket_id"] == "t42"
        assert not errors
    finally:
        page.close()
