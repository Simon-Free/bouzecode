# [desc] Bureau — tiroir Assistant (U10) : choix du dépôt, écho immédiat, action visible sur le Bureau, historique repris qui CONTINUE la conversation, file d'attente + annulation, contexte perso, erreur d'envoi. [/desc]
"""Parcours U10 de SPEC.md, contre le vrai profil `bureau-assistant` piloté par le faux LLM
(`[scn:bureau-tache]` crée une tâche via l'outil Taches, `[scn:slow]` occupe l'assistant)."""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_INFO, TOAST_OK, BASE, attendre, bz_browser, bz_page, ouvrir_bureau, simuler_erreur, api,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/bureau.html",
    "static/css/bureau.css",
    "static/js/bureau/**",
    "static/js/lib/**",
    "static/js/chrome.js",
    "static/ds.css",
    "templates/base.html",
    "static/js/shared/session_thread.js",
    "routes/work/assistant.py",
    "routes/work/fleet.py",
    "routes/sessions/**",
    "services/work/bureau_contexte.py",
    "services/work/file_messages.py",
    "services/work/dispatch.py",
    "services/work/micros.py",
    "runtime/runner/**",
)]
AGENT = 90_000


def _ouvrir(page):
    page.locator("#assistant-bulle").click()
    expect(page.locator("#assistant-drawer")).to_have_attribute("data-open", "true")
    expect(page.locator("#assistant-input")).to_be_focused()


def _envoyer(page, texte):
    page.locator("#assistant-input").fill(texte)
    page.locator("#assistant-input").press("Enter")


def _demarrer(page, texte):
    """Premier message : l'assistant demande son dépôt d'ancrage (aucun « bouzecode » dans le bac
    à sable), on choisit demo-api, la conversation démarre."""
    _envoyer(page, texte)
    choix = page.locator(".bz-assist__projets")
    expect(choix).to_be_visible(timeout=10000)
    expect(page.locator("#assistant-input")).to_have_value(texte)
    choix.get_by_role("button", name=DEPOT).click()
    expect(page.locator(".bz-echo").filter(has_text=texte)).to_be_visible(timeout=5000)
    attendre(lambda: page.evaluate("localStorage.getItem('bureau.assistant')"), 60, 0.5, "conversation démarrée")
    return json.loads(page.evaluate("localStorage.getItem('bureau.assistant')"))


def test_sans_depot_memorise_entree_repetee_ne_repose_pas_la_question(bz_page):
    """Le choix du dépôt est demandé UNE fois : réappuyer sur Entrée (texte remis dans le champ)
    ne doit pas empiler une nouvelle question « Sur quel dépôt… ? » à chaque fois."""
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    for _ in range(3):
        bz_page.locator("#assistant-input").focus()
        _envoyer(bz_page, "Bonjour sans dépôt")
        expect(bz_page.locator(".bz-assist__projets")).to_be_visible(timeout=10000)
    expect(bz_page.locator(".bz-assist__projets")).to_have_count(1)
    expect(bz_page.locator(".bz-echo")).to_have_count(0)


def test_l_assistant_cree_une_tache_visible_sur_le_bureau(bz_page):
    ouvrir_bureau(bz_page, "a_lancer")
    _ouvrir(bz_page)
    avant = {t["id"] for t in _toutes()}
    conv = _demarrer(bz_page, "Crée la tâche du fichier vide [scn:bureau-tache]")
    assert conv["key"].startswith("agent/")
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Tâche créée", timeout=AGENT)
    nouvelles = attendre(lambda: [t for t in _toutes() if t["id"] not in avant
                                  and "fichier vide" in t["titre"]], 60, 1, "tâche créée par l'assistant")
    # Sans recharger : le Bureau se relit à la fin du tour de l'assistant.
    expect(bz_page.locator(f".bz-task[data-id='{nouvelles[0]['id']}']")).to_have_count(1, timeout=20000)


def _reveil_recu(cle: str) -> str:
    """Le message « [Réveil du Bureau] » tel qu'il est entré dans la session de l'assistant."""
    texte = json.dumps(api("GET", f"/api/sessions/{cle}/blocks").get("blocks", []), ensure_ascii=False)
    i = texte.find("[Réveil du Bureau]")
    return texte[i:i + 3000] if i >= 0 else ""


@pytest.mark.parametrize("scenario, attendu", [
    ("bureau-lancer", "TÂCHE FINIE"),
    ("bureau-lancer-question", "Quelle base de données"),
], ids=["fin", "question"])
def test_l_assistant_est_reveille_par_la_tache_qu_il_a_lancee(bz_page, scenario, attendu):
    """TODO 2026-09-25 §6 : une tâche lancée par l'assistant (LancerAgent) lui est rattachée ;
    quand elle finit, ou pose une question, il est réveillé par un message qui NOMME la tâche
    (ticket, agent) et porte le rapport ou la question — sans que l'humain lui reparle."""
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    conv = _demarrer(bz_page, f"Lance un agent [scn:{scenario}]")
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Agent lancé", timeout=AGENT)
    agent_id = conv["key"].split("/", 1)[1]
    enfants = attendre(lambda: api("GET", f"/api/agents/{agent_id}/children").get("children"), 30, 0.5,
                       "tâche rattachée à l'assistant")
    reveil = attendre(lambda: _reveil_recu(conv["key"]), AGENT / 1000, 1, "réveil de l'assistant")
    assert enfants[0]["ticket_id"] in reveil and attendu in reveil, reveil


def test_reprendre_une_conversation_la_continue(bz_page):
    """Historique : reprendre une conversation puis écrire la CONTINUE (même clé d'agent)."""
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    conv = _demarrer(bz_page, "Bonjour l'assistant")
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Bien reçu", timeout=AGENT)
    bz_page.locator("#assistant-nouvelle").click()
    expect(bz_page.locator(".bz-assist__intro")).to_be_visible()
    assert bz_page.evaluate("localStorage.getItem('bureau.assistant')") is None
    hist = bz_page.locator("#assistant-historique")
    expect(hist.locator(f"option[value='{conv['key']}']")).to_have_count(1, timeout=20000)
    hist.select_option(conv["key"])
    expect(bz_page.locator("#assistant-status")).to_contain_text("Conversation reprise")
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Bonjour l'assistant", timeout=20000)
    _envoyer(bz_page, "Et maintenant ?")
    expect(bz_page.locator(".bz-echo").filter(has_text="Et maintenant ?")).to_be_visible()
    reprise = json.loads(bz_page.evaluate("localStorage.getItem('bureau.assistant')"))
    assert reprise["key"] == conv["key"], "le message a ouvert une nouvelle conversation"
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Et maintenant ?", timeout=AGENT)


def test_message_pendant_que_l_assistant_travaille_est_mis_en_file(bz_page):
    """Pas d'interruption implicite : un message envoyé pendant son tour attend (« en attente »,
    lu à sa prochaine étape), et « Annuler » le retire et le remet dans le champ."""
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    _demarrer(bz_page, "Réfléchis longuement [scn:slow]")
    expect(bz_page.locator("#assistant-status")).not_to_have_text("", timeout=AGENT)
    _envoyer(bz_page, "Deuxième message")
    echo = bz_page.locator(".bz-echo").filter(has_text="Deuxième message")
    expect(echo.locator(".bz-echo__etat")).to_contain_text("en attente", timeout=15000)
    echo.get_by_role("button", name="Annuler").click()
    expect(bz_page.locator(TOAST_INFO).filter(has_text="Message retiré")).to_be_visible(timeout=10000)
    expect(bz_page.locator(".bz-echo").filter(has_text="Deuxième message")).to_have_count(0)
    expect(bz_page.locator("#assistant-input")).to_have_value("Deuxième message")


def test_echec_d_envoi_garde_le_message(bz_page):
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    bz_page.evaluate(f"localStorage.setItem('bureau.assistant.projet', '{DEPOT}')")
    simuler_erreur(bz_page, "**/api/projects/*/tickets", 500, methode="POST")
    _envoyer(bz_page, "Ce message échoue")
    echo = bz_page.locator(".bz-echo").filter(has_text="Ce message échoue")
    expect(echo).to_have_class("bz-echo bz-echo--ko", timeout=10000)
    expect(echo).to_contain_text("non envoyé")
    expect(bz_page.locator("#assistant-input")).to_have_value("Ce message échoue")
    expect(bz_page.locator("#assistant-send")).to_be_enabled()


def test_contexte_perso(bz_page):
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    bz_page.locator("#assistant-reglages").click()
    zone = bz_page.locator("#assistant-contexte")
    expect(zone).to_be_visible()
    expect(zone).to_be_enabled(timeout=10000)
    ancien = zone.input_value()
    zone.fill(ancien + "\nJe travaille sur demo-api.")
    expect(bz_page.locator("#assistant-contexte-flag")).to_have_text("• modifié")
    bz_page.locator("#assistant-contexte-save").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Contexte enregistré")).to_be_visible(timeout=10000)
    expect(bz_page.locator("#assistant-contexte-flag")).to_have_text("")
    assert "Je travaille sur demo-api." in api("GET", "/api/bureau/assistant/contexte")["contenu"]
    zone.fill(ancien)
    bz_page.locator("#assistant-contexte-save").click()
    expect(bz_page.locator("#assistant-contexte-flag")).to_have_text("", timeout=10000)


def _toutes():
    d = api("GET", "/api/lignes")
    return [t for c in d["chantiers"] for t in c["lignes"]] + d["non_rattachees"]
