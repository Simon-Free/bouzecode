# [desc] Champs de message (panneau d'un agent, assistant du Bureau) : Entrée les vide AUSSITÔT (focus gardé) pendant que le serveur traite l'envoi ; un échec remet le texte. [/desc]
"""TODO 2026-09-25 §1 — « le message part bien, mais le texte RESTE dans la zone de saisie ».

Le champ n'était vidé qu'au RETOUR de `POST /messages` (ex-`/continue`). Or ce POST relance l'agent
(respawn d'un process, re-homing du worktree) : plusieurs secondes sous Windows, jusqu'à
60 s de délai client. Pendant tout ce temps l'écho « envoi… » était déjà dans le fil ET le
texte toujours dans le champ : l'utilisateur voyait son message « parti » mais pas effacé.

POURQUOI UN NAVIGATEUR : c'est une vraie frappe Entrée dans le panneau construit par le
JavaScript (onglet ouvert par lien profond, poller /blocks en marche), et la valeur/le focus
du textarea pendant une requête EN VOL — que seul un vrai moteur prouve.

La requête `/messages` est interceptée et laissée en suspens : on observe le champ pendant
que le serveur « travaille », puis on la termine (succès ou échec).
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

AGENT = "a1f00d"
BLOCKS = {"blocks": [], "total": 0, "status": {"state": "finished"}, "queue": []}


def _ouvrir_agent(page, server):
    """Ouvre le panneau de l'agent (lien profond) ; /blocks et /messages sont simulés."""
    en_vol: list = []
    page.route(f"**/api/sessions/agent/{AGENT}/blocks*",
               lambda r: r.fulfill(status=200, body=json.dumps(BLOCKS), content_type="application/json"))
    page.route(f"**/api/agents/{AGENT}/messages", lambda r: en_vol.append(r))
    page.goto(f"{server}/conversations?agent={AGENT}", wait_until="domcontentloaded")
    champ = page.locator(".ag-composer__input")
    expect(champ).to_be_enabled(timeout=15000)
    expect(page.locator(".ag-composer__send")).to_have_text("Envoyer")
    return champ, en_vol


def _attendre_envoi(page, en_vol):
    """Attend que le POST parte (il reste en suspens tant que le test ne le termine pas)."""
    for _ in range(50):
        if en_vol:
            return en_vol[0]
        page.wait_for_timeout(100)
    raise AssertionError("aucun POST /messages parti")


def test_entree_vide_le_champ_des_l_envoi_et_garde_le_focus(server, page):
    champ, en_vol = _ouvrir_agent(page, server)
    champ.fill("et après ?")
    champ.press("Enter")
    requete = _attendre_envoi(page, en_vol)
    # Le serveur n'a pas encore répondu : l'écho dit « envoi… » et le champ est DÉJÀ vide.
    expect(page.locator(".ag-echo")).to_contain_text("et après ?")
    expect(champ).to_have_value("")
    assert json.loads(requete.request.post_data or "{}").get("text") == "et après ?"
    requete.fulfill(status=200, body='{"ok": true, "delivered": true}', content_type="application/json")
    expect(page.locator(".ag-echo")).to_contain_text("envoyé")
    expect(champ).to_have_value("")
    expect(champ).to_be_focused()
    # Le champ est aussitôt réutilisable pour le message suivant.
    champ.press_sequentially("suite")
    expect(champ).to_have_value("suite")


def test_echec_d_envoi_remet_le_texte_dans_le_champ(server, page):
    champ, en_vol = _ouvrir_agent(page, server)
    champ.fill("ce message échoue")
    champ.press("Enter")
    requete = _attendre_envoi(page, en_vol)
    expect(champ).to_have_value("")
    requete.fulfill(status=500, body='{"error": "panne simulée"}', content_type="application/json")
    expect(page.locator(".ag-composer__error")).to_contain_text("panne simulée")
    expect(champ).to_have_value("ce message échoue")
    expect(champ).to_be_focused()
    expect(page.locator(".ag-echo")).to_have_count(0)


# ---------------------------------------------------------------- assistant du Bureau (même défaut)

ASSISTANT = "b0bcafe"


def test_assistant_du_bureau_vide_le_champ_des_l_envoi(server, page):
    """Le tiroir Assistant du Bureau avait le même défaut : champ vidé au retour du serveur."""
    en_vol: list = []
    page.add_init_script(
        f"localStorage.setItem('bureau.assistant', JSON.stringify({{key: 'agent/{ASSISTANT}', ticket_id: ''}}))")
    page.route(f"**/api/sessions/agent/{ASSISTANT}/blocks*",
               lambda r: r.fulfill(status=200, body=json.dumps(BLOCKS), content_type="application/json"))
    page.route(f"**/api/agents/{ASSISTANT}/messages", lambda r: en_vol.append(r))
    page.goto(f"{server}/bureau", wait_until="domcontentloaded")
    page.locator("#assistant-bulle").click()
    champ = page.locator("#assistant-input")
    expect(champ).to_be_focused()
    champ.fill("Deuxième message")
    champ.press("Enter")
    requete = _attendre_envoi(page, en_vol)
    expect(page.locator(".bz-echo")).to_contain_text("Deuxième message")
    expect(champ).to_have_value("")
    requete.fulfill(status=200, body='{"ok": true, "delivered": true}', content_type="application/json")
    expect(page.locator(".bz-echo")).to_contain_text("envoyé")
    expect(champ).to_have_value("")
    expect(champ).to_be_focused()
