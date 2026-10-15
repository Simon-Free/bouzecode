# [desc] E2E page Agents — chemins d'erreur de chaque action : lancement échoué en arrière-plan puis Réessayer, réponse à une question refusée, Arrêter / Continuer / Restaurer refusés, vues en panne, archivage d'un agent qui travaille, fermeture d'onglet (R4, R5, R6). [/desc]
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from agents_e2e_support import (  # noqa: F401 — fixtures importées
    BASE, MARQUES, Retenue, TOAST_ERR, TOAST_OK, api, attendre_etat, browser, cle_agent, expect, lancer,
    ouvrir, ouvrir_agent, panneau, pg, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre("static/js/conversations.js", "static/js/conversations/**", "static/css/agents.css", "templates/conversations.html", "templates/base.html", "static/js/lib/**", "static/js/chrome.js", "static/ds.css", "static/js/shared/**", "routes/sessions/**", "routes/work/fleet.py", "services/work/fleet.py", "services/work/lexique.py", "services/sessions/**", "runtime/**", "services/work/dispatch.py", "services/work/launch_phase.py", "routes/work/projects.py", "routes/tickets_api/**", "services/work/file_messages.py")]

#  Dossier du dépôt disparu : « No such file » sous POSIX, « [WinError 267] Nom de répertoire
#  non valide » (ou WinError 2/3) sous Windows.
DOSSIER_ABSENT = re.compile(r"No such file|WinError (2|3|267)\b")

JSON = "application/json"


def _panne(page, motif, status=500, message="panne simulée"):
    page.route(motif, lambda r: r.fulfill(status=status, body=f'{{"error":"{message}"}}', content_type=JSON))


def test_lancement_echoue_en_arriere_plan_puis_reessayer(pg, tmp_path):
    """U11 (échec) : l'onglet dit « Lancement échoué : raison », la liste le met « À traiter »,
    « Réessayer le lancement » repart avec la même demande et réussit une fois la cause levée."""
    dossier = tmp_path / uid("depot-disparu")
    dossier.mkdir()
    nom = dossier.name
    projet = api("POST", "/api/projects", {"name": nom, "path": str(dossier)}, attendu=201)
    shutil.rmtree(dossier)
    #  Dossier non git : la barre demande `worktree` (défaut), le serveur répond 400
    #  `isolation_impossible`, la barre le dit et relance en `shared` (launcher.js) — un 400 ATTENDU.
    pg.autoriser(r"status of 400")
    try:
        page = pg.page
        page.goto(f"{BASE}/conversations")
        page.evaluate(f"localStorage.setItem('bz.conv.project', '{projet['slug']}')")
        page.reload()
        expect(page.locator("#ag-chip-repo")).to_contain_text(nom)
        titre = uid("Echec")
        page.fill("#conv-new-input", f"{titre}\n[scn:reply]")
        page.click("#conv-new-send")
        p = panneau(pg)
        err = p.locator(".error-state", has_text="Lancement échoué")
        expect(err).to_be_visible(timeout=30000)
        expect(err).to_contain_text(DOSSIER_ABSENT)
        expect(p.locator(".ag-head .badge")).to_contain_text("Lancement échoué")
        expect(p.locator(".ag-composer__input")).to_be_disabled()
        expect(page.locator(".ag-group[data-group=a_traiter] .ag-card", has_text=titre)).to_be_visible(timeout=30000)
        # La cause est levée : Réessayer repart avec la MÊME demande et l'agent répond.
        Path(dossier).mkdir()
        retry = p.locator(".ag-head__actions button", has_text="Réessayer le lancement")
        retry.click()
        expect(page.locator(TOAST_OK, has_text="Nouveau lancement")).to_be_visible(timeout=30000)
        expect(p.locator(".block.final-answer")).to_be_visible(timeout=60000)
        expect(p.locator(".block.user")).to_contain_text(titre)
    finally:
        api("DELETE", f"/api/projects/{projet['slug']}")


def test_reponse_a_une_question_refusee_options_rendues_et_erreur_dite(pg):
    key = cle_agent(lancer(uid("QErr"), "question"))
    attendre_etat(key, {"awaiting_input"})
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    pg.autoriser(r"status of 500")
    _panne(page, "**/messages")
    q = p.locator(".ag-question")
    expect(q).to_contain_text("Quelle base")
    q.locator(".ag-question__option", has_text="PostgreSQL").click()
    expect(q).to_contain_text("n'est pas partie")
    expect(q.locator(".ag-question__option").first).to_be_enabled()
    expect(p.locator(".ag-echo--error")).to_contain_text("panne simulée")
    # Réessayer depuis l'écho, serveur rétabli.
    page.unroute("**/messages")
    p.locator(".ag-echo--error button", has_text="Réessayer").click()
    expect(p.locator(".block.final-answer")).to_contain_text("Choix pris en compte", timeout=60000)


def test_arreter_refuse_toast_d_erreur_et_bouton_rendu(pg):
    key = cle_agent(lancer(uid("StopErr"), "slow"))
    attendre_etat(key, {"running"}, delai=40)
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    pg.autoriser(r"status of 500")
    _panne(page, "**/interruptions", message="le système a refusé")
    stop = p.locator(".ag-head__actions button", has_text="Arrêter")
    expect(stop).to_be_visible(timeout=20000)
    stop.click()
    page.locator("dialog.ui-dialog button", has_text="Arrêter").click()
    expect(page.locator(TOAST_ERR)).to_contain_text("le système a refusé")
    expect(stop).to_be_enabled()
    expect(stop).not_to_have_attribute("aria-busy", "true")


def test_continuer_refuse_erreur_dite(pg):
    key = cle_agent(lancer(uid("ContErr"), "crash"))
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    cont = p.locator(".ag-head__actions button", has_text="Continuer")
    expect(cont).to_be_visible(timeout=60000)
    pg.autoriser(r"status of 409")
    _panne(page, "**/messages", status=409, message="un process tourne déjà")
    cont.click()
    expect(page.locator(TOAST_ERR)).to_contain_text("un process tourne déjà")
    expect(cont).to_be_enabled()


def test_vues_en_panne_puis_reessayer(pg):
    key = cle_agent(lancer(uid("VuesErr"), "recap"))
    attendre_etat(key, {"finished", "idle"})
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    pg.autoriser(r"status of 500")
    _panne(page, "**/recap", message="récap illisible")
    _panne(page, "**/files?raw=1", message="diffs illisibles")
    p.locator(".ag-views .tab", has_text="Récap").click()
    expect(p.locator(".ag-pane--recap .error-state")).to_contain_text("récap illisible")
    page.unroute("**/recap")
    p.locator(".ag-pane--recap .error-state button", has_text="Réessayer").click()
    expect(p.locator(".ag-pane--recap")).to_contain_text("UTF-8", timeout=20000)
    p.locator(".ag-views .tab", has_text="Fichiers modifiés").click()
    expect(p.locator(".ag-pane--files .error-state")).to_contain_text("diffs illisibles")
    page.unroute("**/files?raw=1")
    p.locator(".ag-pane--files .error-state button", has_text="Réessayer").click()
    expect(p.locator(".ag-pane--files .error-state")).to_have_count(0, timeout=20000)


def test_restauration_refusee_erreur_dite(pg):
    titre = uid("RestErr")
    key = cle_agent(lancer(titre, "reply"))
    attendre_etat(key, {"finished", "idle"})
    api("POST", "/api/conversations/archive", {"keys": [key]}, attendu=200)
    ouvrir(pg)
    page = pg.page
    pg.autoriser(r"status of 500")
    _panne(page, "**/restore", message="corbeille verrouillée")
    page.locator(".ag-group--archived .ag-group__toggle").click()
    carte = page.locator(".ag-group--archived .ag-card", has_text=titre)
    expect(carte).to_be_visible(timeout=30000)
    carte.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Restaurer").click()
    expect(page.locator(TOAST_ERR)).to_contain_text("corbeille verrouillée")
    page.unroute("**/restore")
    api("POST", f"/api/sessions/{key}/restore")


def test_archiver_un_agent_qui_travaille_demande_confirmation_et_l_arrete(pg):
    titre = uid("ArchRun")
    key = cle_agent(lancer(titre, "slow"))
    attendre_etat(key, {"running"}, delai=40)
    ouvrir(pg)
    page = pg.page
    carte = page.locator(".ag-group[data-group=en_cours] .ag-card", has_text=titre).first
    expect(carte).to_be_visible(timeout=30000)
    carte.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Archiver").click()
    dlg = page.locator("dialog.ui-dialog")
    expect(dlg).to_contain_text("travaille")
    dlg.locator("button", has_text="Annuler").click()
    assert pg.appels(r"/stop") == [] and pg.appels(r"/conversations/archive") == []
    carte.locator(".ag-card__more").click()
    page.locator(".menu__item", has_text="Archiver").click()
    page.locator("dialog.ui-dialog button", has_text="Arrêter et archiver").click()
    expect(page.locator(TOAST_OK, has_text="archivé")).to_be_visible(timeout=30000)
    assert pg.appels(r"/stop", "POST")


def test_fermer_un_onglet_a_la_souris_revient_a_l_etat_vide(pg):
    key = cle_agent(lancer(uid("Ferme"), "reply"))
    ouvrir_agent(pg, key)
    page = pg.page
    page.locator(".ag-tab[aria-selected=true] .ag-tab__close").click()
    expect(page.locator(".ag-tab")).to_have_count(0)
    expect(page.locator(".ag-empty")).to_be_visible()
    assert "agent=" not in page.url


def test_recherche_occupee_puis_effacement_par_la_croix(pg):
    ouvrir(pg)
    page = pg.page
    retenue = Retenue(page, "**/api/search*")
    page.fill("#ag-filter", "Refactore")
    page.press("#ag-filter", "Enter")
    expect(page.locator("#ag-search-results .spinner")).to_be_visible()
    retenue.relacher()
    expect(page.locator("#ag-search-results")).not_to_have_attribute("aria-busy", "true")
    page.locator("#ag-filter-clear").click()
    expect(page.locator("#ag-filter")).to_have_value("")
    expect(page.locator("#ag-search-results")).to_be_hidden()
    expect(page.locator("#ag-filter")).to_be_focused()
