"""Carte « signalement » hors tâche du Bureau : on doit pouvoir la retirer.

Bug : un signalement dont l'agent est un pseudo-agent de process (`process:4392`, sans fiche)
n'offrait que « Ouvrir la conversation », qui mène à un agent introuvable — la carte restait
coincée dans « Ce qui t'attend ». La carte doit proposer « Acquitter »
(POST /api/signalements/<id>/acquitter) et ne pas ouvrir une conversation inexistante.

Playwright car c'est l'exécution réelle du module JS (pas de node dans l'environnement)."""
from __future__ import annotations

import json

# Forme réelle relevée sur /api/inbox (inbox_signalements.cartes).
SIGNALEMENT = {"type": "signalement", "id": "signalement:s1", "signalement_id": "s1",
               "titre": "Proxy KO", "agent_id": "process:4392", "key": "process:4392",
               "projet_slug": "", "tache": None, "actions": ["acquitter", "ouvrir"]}

_LIBELLES = """async (item) => {
  const m = await import('/static/js/bureau/inbox_carte.js');
  const box = document.createElement('div');
  box.id = 'carte-test';
  m.contenuCarte(item).forEach((n) => box.appendChild(n));
  document.body.appendChild(box);
  return [...box.querySelectorAll('button, a')].map((b) => b.textContent.trim());
}"""


def _page(browser, server):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{server}/", wait_until="domcontentloaded")
    return page, errors


def test_signalement_process_propose_acquitter_sans_ouvrir(browser, server):
    page, errors = _page(browser, server)
    try:
        libelles = page.evaluate(_LIBELLES, SIGNALEMENT)
        assert "Acquitter" in libelles
        assert "Ouvrir la conversation" not in libelles
        assert not errors
    finally:
        page.close()


def test_signalement_vrai_agent_garde_ouvrir(browser, server):
    page, errors = _page(browser, server)
    try:
        libelles = page.evaluate(_LIBELLES, {**SIGNALEMENT, "agent_id": "a12", "key": "a12"})
        assert "Acquitter" in libelles
        assert "Ouvrir la conversation" in libelles
        assert not errors
    finally:
        page.close()


def test_acquitter_poste_sur_l_api(browser, server):
    page, errors = _page(browser, server)
    appels = []

    def _capture(route):
        appels.append((route.request.method, route.request.url))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

    page.route("**/api/signalements/*/acquitter", _capture)
    try:
        page.evaluate(_LIBELLES, SIGNALEMENT)
        page.locator("#carte-test button", has_text="Acquitter").click()
        page.wait_for_function("() => true")
        page.wait_for_timeout(500)
        assert appels and appels[0][0] == "POST"
        assert "/api/signalements/s1/acquitter" in appels[0][1]
        assert not errors
    finally:
        page.close()
