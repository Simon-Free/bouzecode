# [desc] E2E page Agents — liste : chargement (squelette puis groupes), filtre et recherche plein texte, archivage avec Annuler, restauration, sous-agents repliables, clavier, panne de chargement, serveur coupé (U12, U15, U16). [/desc]
from __future__ import annotations

import re

import pytest

from agents_e2e_support import (  # noqa: F401 — fixtures importées
    BASE, MARQUES, Retenue, TOAST_ERR, TOAST_OK, api, attendre_etat, browser, cle_agent, expect, lancer, ouvrir, panneau, pg, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre("static/js/conversations.js", "static/js/conversations/**", "static/css/agents.css", "templates/conversations.html", "templates/base.html", "static/js/lib/**", "static/js/chrome.js", "static/ds.css", "static/js/shared/**", "routes/sessions/**", "routes/work/fleet.py", "services/work/fleet.py", "services/work/lexique.py", "services/sessions/**", "runtime/**", "routes/search.py", "services/search.py", "services/sessions/purge.py")]


def test_chargement_squelette_puis_groupes_sans_maintenance_silencieuse(pg):
    """U16 + R2 + R11 : squelette pendant le chargement, groupes avec compteurs ensuite, aucune purge."""
    page = pg.page
    retenue = Retenue(page, re.compile(r"/api/agents/tree\?offset=0"))
    page.goto(f"{BASE}/conversations", wait_until="domcontentloaded")
    expect(page.locator("#conv-list .skeleton")).to_be_visible()
    expect(page.locator("#conv-list")).to_have_attribute("aria-busy", "true")
    retenue.relacher()
    expect(page.locator(".ag-group").first).to_be_visible(timeout=20000)
    # Chaque groupe visible porte un compteur ; « Archivés » existe, replié.
    for g in page.locator(".ag-group:not(.ag-group--archived)").all():
        expect(g.locator(".count")).not_to_have_text("")
    expect(page.locator(".ag-group--archived .ag-group__toggle")).to_have_attribute("aria-expanded", "false")
    # R11 : aucune maintenance silencieuse au chargement.
    assert pg.appels(r"auto-purge|auto-archive|purge-tests") == []
    # R12 : le titre d'onglet nomme la page.
    assert "Agents" in page.title()


def test_etat_toujours_lisible_en_toutes_lettres(pg):
    """§1.1 : un état n'est jamais porté par la seule couleur — libellé ou icône + libellé accessible."""
    ouvrir(pg)
    badges = pg.page.locator(".ag-card .badge")
    assert badges.count() > 0
    for b in badges.all()[:20]:
        assert b.locator(".badge__label").inner_text().strip() != ""
        assert b.locator(".badge__icon").inner_text().strip() != ""


def test_filtre_instantane_effacement_et_echap(pg):
    titre = uid("Filtre")
    t = lancer(titre, "reply")
    cle_agent(t)
    ouvrir(pg)
    page = pg.page
    expect(page.locator(".ag-card", has_text=titre)).to_be_visible(timeout=20000)
    page.fill("#ag-filter", titre)
    # Instantané : pas d'aller-retour serveur pour filtrer les agents chargés.
    expect(page.locator(".ag-group:not(.ag-group--archived) .ag-card")).to_have_count(1)
    expect(page.locator("#ag-filter-clear")).to_be_visible()
    page.fill("#ag-filter", "zzz-aucun-agent-zzz")
    expect(page.locator(".ag-list__empty")).to_contain_text("Aucun agent ne correspond")
    page.press("#ag-filter", "Escape")
    expect(page.locator("#ag-filter")).to_have_value("")
    expect(page.locator(".ag-card", has_text=titre)).to_be_visible()
    # « / » donne le focus à la recherche.
    page.locator("body").click(position={"x": 5, "y": 300})
    page.keyboard.press("/")
    expect(page.locator("#ag-filter")).to_be_focused()


def test_recherche_plein_texte_etat_resultats_ouverture_et_erreur(pg):
    titre = uid("Plein texte")
    t = lancer(titre, "reply")
    key = cle_agent(t)
    attendre_etat(key, {"finished", "idle"})
    ouvrir(pg)
    page = pg.page

    retenue = Retenue(page, "**/api/search*")
    page.fill("#ag-filter", titre)
    page.press("#ag-filter", "Enter")
    expect(page.locator("#ag-search-results")).to_contain_text("Recherche de")
    expect(page.locator("#ag-search-results")).to_have_attribute("aria-busy", "true")
    retenue.relacher()
    expect(page.locator(".ag-search-hit").first).to_be_visible(timeout=15000)
    page.locator(".ag-search-hit").first.click()
    expect(panneau(pg).locator(".ag-head__title")).to_contain_text(titre)
    # Erreur de recherche : dite, avec Réessayer.
    pg.autoriser(r"status of 500")
    page.route("**/api/search*", lambda r: r.fulfill(status=500, body='{"error":"boom"}', content_type="application/json"))
    page.press("#ag-filter", "Enter")
    expect(page.locator("#ag-search-results .error-state")).to_contain_text("Recherche impossible")
    page.unroute("**/api/search*")
    page.locator("#ag-search-results .error-state button").click()
    expect(page.locator(".ag-search-hit").first).to_be_visible(timeout=15000)


def test_archiver_annuler_puis_restaurer_depuis_archives(pg):
    """U12 : effet immédiat, toast « Annuler », groupe Archivés, Restaurer."""
    titre = uid("Archive")
    key = cle_agent(lancer(titre, "reply"))
    attendre_etat(key, {"finished", "idle"})
    ouvrir(pg)
    page = pg.page
    carte = page.locator(".ag-card", has_text=titre).first
    expect(carte).to_be_visible(timeout=20000)
    carte.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Archiver").click()
    expect(page.locator(".ag-group:not(.ag-group--archived) .ag-card", has_text=titre)).to_have_count(0)
    toast = page.locator(TOAST_OK, has_text="archivé")
    expect(toast).to_be_visible()
    toast.locator(".toast__action", has_text="Annuler").click()
    expect(page.locator(TOAST_OK, has_text="restauré")).to_be_visible()
    expect(page.locator(".ag-group:not(.ag-group--archived) .ag-card", has_text=titre)).to_be_visible(timeout=20000)
    # Archiver à nouveau, puis restaurer depuis le groupe « Archivés ».
    carte = page.locator(".ag-group:not(.ag-group--archived) .ag-card", has_text=titre).first
    carte.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Archiver").click()
    expect(page.locator(TOAST_OK, has_text="archivé").last).to_be_visible()
    page.locator(".ag-group--archived .ag-group__toggle").click()
    archivee = page.locator(".ag-group--archived .ag-card", has_text=titre)
    expect(archivee).to_be_visible(timeout=30000)
    expect(archivee.locator(".badge")).to_contain_text("Archivé")
    archivee.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Restaurer").click()
    expect(page.locator(TOAST_OK, has_text="restauré").last).to_be_visible()
    expect(page.locator(".ag-group:not(.ag-group--archived) .ag-card", has_text=titre)).to_be_visible(timeout=20000)


def test_archivage_refuse_la_carte_revient_et_l_erreur_est_dite(pg):
    titre = uid("ArchiveKO")
    key = cle_agent(lancer(titre, "reply"))
    attendre_etat(key, {"finished", "idle"})
    ouvrir(pg)
    page = pg.page
    pg.autoriser(r"status of 500")
    page.route("**/api/conversations/archive", lambda r: r.fulfill(status=500, body='{"error":"disque plein"}', content_type="application/json"))
    carte = page.locator(".ag-card", has_text=titre).first
    expect(carte).to_be_visible(timeout=20000)
    # La liste suit l'état par son propre sondage : tant qu'elle montre encore l'agent
    # « En cours », Archiver demande d'abord confirmation (arrêt) au lieu d'archiver.
    expect(page.locator(".ag-group[data-group='en_cours'] .ag-card", has_text=titre)).to_have_count(0, timeout=20000)
    carte.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Archiver").click()
    expect(page.locator(TOAST_ERR)).to_contain_text("disque plein")
    expect(page.locator(".ag-card", has_text=titre).first).to_be_visible()


def test_sous_agents_repliables_et_marqueurs_cliquables(pg):
    titre = uid("Manager")
    key = cle_agent(lancer(titre, "subagents"))
    ouvrir(pg)
    page = pg.page
    # La carte du manager lui-même (pas la carte « ↳ sous-agent de … » qui cite son titre).
    carte = page.locator(".ag-group:not(.ag-group--archived) > .ag-group__body > .ag-card").filter(
        has=page.locator(":scope > .ag-card__row .ag-card__title", has_text=titre)).first
    toggle = carte.locator(".ag-card__kids-toggle")
    expect(toggle).to_contain_text("2 sous-agents", timeout=60000)
    ouvert = toggle.get_attribute("aria-expanded") == "true"
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false" if ouvert else "true")
    if ouvert:
        toggle.click()
    expect(carte.locator(".ag-card__kids .ag-card")).to_have_count(2)
    # Le sous-agent qui pose une question remonte en propre dans « À traiter » ; son parent est
    # cité au survol (la carte ne garde que titre + une ligne).
    expect(page.locator(f".ag-group[data-group=a_traiter] .ag-card__main[title*='sous-agent de « {titre} »']")).to_contain_text(
        "Sous-tâche B", timeout=60000)
    # Ouvrir un sous-agent depuis la carte du manager.
    carte.locator(".ag-card__kids .ag-card__main").first.click()
    expect(panneau(pg).locator(".ag-head__title")).to_contain_text("Sous-tâche")
    del key


def test_liste_au_clavier_carte_menu_et_onglet(pg):
    titre = uid("Clavier")
    key = cle_agent(lancer(titre, "reply"))
    attendre_etat(key, {"finished", "idle"})
    ouvrir(pg)
    page = pg.page
    main = page.locator(".ag-card", has_text=titre).first.locator(".ag-card__main")
    expect(main).to_be_visible(timeout=20000)
    main.focus()
    page.keyboard.press("Enter")
    expect(panneau(pg).locator(".ag-head__title")).to_contain_text(titre)
    more = page.locator(".ag-card", has_text=titre).first.locator(".ag-card__more")
    more.focus()
    page.keyboard.press("ArrowDown")
    expect(page.locator(".menu__list")).to_be_visible()
    expect(page.locator(".menu__item").first).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator(".menu__list")).to_have_count(0)
    expect(more).to_be_focused()


def test_panne_au_chargement_puis_reessayer(pg):
    """R4 : jamais « Chargement… » éternel — état d'erreur + Réessayer qui fonctionne."""
    page = pg.page
    pg.autoriser(r"status of 503")
    page.route(re.compile(r"/api/agents/tree\?offset=0"), lambda r: r.fulfill(status=503, body='{"error":"serveur surchargé"}', content_type="application/json"))
    page.goto(f"{BASE}/conversations")
    err = page.locator("#conv-list .error-state")
    expect(err).to_contain_text("Impossible de charger la liste des agents")
    expect(err).to_contain_text("serveur surchargé")
    page.unroute(re.compile(r"/api/agents/tree\?offset=0"))
    err.locator("button", has_text="Réessayer").click()
    expect(page.locator(".ag-group").first).to_be_visible(timeout=20000)


def test_serveur_coupe_bandeau_puis_retour_automatique(pg):
    """U15 / R7 : deux échecs réseau → bandeau « connexion perdue » ; retour → il disparaît."""
    ouvrir(pg)
    page = pg.page
    pg.autoriser(r"ERR_|net::|Failed to load|failed")
    page.route("**/api/**", lambda r: r.abort("connectionrefused"))
    # Force des rafraîchissements : filtre plein texte + recherche, puis attente du poll.
    page.fill("#ag-filter", "abc")
    page.press("#ag-filter", "Enter")
    page.press("#ag-filter", "Enter")
    expect(page.locator("#offline-banner")).to_be_visible(timeout=30000)
    expect(page.locator("#offline-banner")).to_contain_text("Connexion au serveur perdue")
    page.unroute("**/api/**")
    page.locator("#offline-banner [data-offline-retry]").click()
    expect(page.locator("#offline-banner")).to_be_hidden(timeout=15000)
