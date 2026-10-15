# [desc] Bureau — classer une tâche sans la lancer depuis le menu ⋯ : « Doublon de… », « Marquer faite… », « Caduque… » avec un commentaire ; la carte et les archivées disent pourquoi, qui et quand ; Annuler (toast) rouvre en gardant l'historique ; menu désactivé tant qu'un agent travaille. [/desc]
"""Parcours U22 (SPEC §4.6, §7). Chaque test crée son chantier et ses tâches sous un nom unique."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_OK, api, attendre, bz_browser, bz_page, creer_chantier, creer_tache, deplier,
    ligne, ouvrir_archives, ouvrir_bureau, section_statut, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/bureau.html",
    "static/css/bureau.css",
    "static/js/bureau/**",
    "static/js/lib/**",
    "routes/work/micros/**",
    "services/work/classement.py",
    "services/work/taches_*.py",
    "services/work/bureau_lignes.py",
)]
QUAND = r"\d\d/\d\d \d\d:\d\d"


def _menu(page, micro_id: str, entree: str):
    tache = deplier(page, micro_id)
    tache.get_by_role("button", name="Autres actions sur la tâche").click()
    return page.get_by_role("menuitem", name=entree)


def _archivee(page, micro_id: str):
    ouvrir_archives(page)
    return section_statut(page, "archivees").locator(f".bz-task[data-id='{micro_id}']")


def test_doublon_de_depuis_le_menu_puis_annuler(bz_page):
    c = creer_chantier()
    gardee = creer_tache(uid("Étendre le scraping"), macro_id=c["id"])
    doublon = creer_tache(uid("Brancher d'autres sites"), macro_id=c["id"])
    ouvrir_bureau(bz_page)

    _menu(bz_page, doublon["id"], "Doublon de…").click()
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    expect(dlg).to_contain_text(doublon["titre"])
    dlg.get_by_role("button", name="Marquer doublon").click()
    expect(dlg.get_by_role("alert")).to_have_text("Choisis la tâche dont c'est le doublon.")
    dlg.get_by_label("Doublon de la tâche").select_option(gardee["id"])
    dlg.get_by_label("Commentaire").fill("même sujet, on garde l'autre")
    dlg.get_by_role("button", name="Marquer doublon").click()

    toast = bz_page.locator(TOAST_OK).filter(has_text=f"Doublon de « {gardee['titre']} »")
    expect(toast).to_be_visible(timeout=10000)
    carte = _archivee(bz_page, doublon["id"])
    expect(carte.locator(".bz-task__badge")).to_contain_text("Doublon")
    expect(carte.locator(".bz-task__meta")).to_have_text(re.compile(
        rf"^Doublon de « {re.escape(gardee['titre'])} » — même sujet, on garde l'autre \(ton commentaire, {QUAND}\)$"))
    assert ligne(doublon["id"])["classement"]["auteur"] == "humain"

    toast.get_by_role("button", name="Annuler").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche rouverte")).to_be_visible(timeout=10000)
    rouverte = attendre(lambda: (lambda t: t if t["statut_ui"] == "brouillon" else None)(ligne(doublon["id"])),
                        20, message="la tâche n'est pas rouverte")
    assert rouverte["classement"] is None and rouverte["classements"][0]["rouvert_at"]
    deplier(bz_page, doublon["id"])
    expect(tache_loc(bz_page, doublon["id"]).locator(".bz-classement")).to_contain_text("rouverte", timeout=10000)


def test_marquer_faite_et_caduque_avec_commentaire_visibles_dans_les_archivees(bz_page):
    c = creer_chantier()
    faite = creer_tache(uid("Exporter les verdicts"), macro_id=c["id"])
    caduque = creer_tache(uid("Trancher le worktree"), macro_id=c["id"])
    ouvrir_bureau(bz_page)

    _menu(bz_page, faite["id"], "Marquer faite…").click()
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    dlg.get_by_label("Commentaire").fill("fait par l'export data/state.json")
    dlg.get_by_role("button", name="Marquer faite").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Faite")).to_be_visible(timeout=10000)
    _menu(bz_page, caduque["id"], "Caduque…").click()
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    dlg.get_by_label("Commentaire").fill("le worktree n'existe plus")
    dlg.get_by_role("button", name="Marquer caduque").click()

    expect(_archivee(bz_page, caduque["id"]).locator(".bz-task__meta")).to_have_text(
        re.compile(rf"^Caduque — le worktree n'existe plus \(ton commentaire, {QUAND}\)$"), timeout=10000)
    expect(_archivee(bz_page, faite["id"]).locator(".bz-task__meta")).to_have_text(
        re.compile(rf"^Faite — fait par l'export data/state.json \(ton commentaire, {QUAND}\)$"))


def test_le_commentaire_de_l_assistant_se_lit_sur_la_carte(bz_page):
    """L'assistant classe par l'API (outil Taches) : la carte le signe « commentaire de l'assistant »."""
    c = creer_chantier()
    principale = creer_tache(uid("Scraper les énigmes"), macro_id=c["id"])
    suite = creer_tache(uid("Corriger les 10 points"), macro_id=c["id"])
    api("POST", f"/api/micros/{suite['id']}/classer", {
        "motif": "faite", "de": principale["id"], "auteur": "assistant",
        "commentaire": "fait lors du tour de retours du 25/09"}, attendu=200)

    ouvrir_bureau(bz_page)

    expect(_archivee(bz_page, suite["id"]).locator(".bz-task__meta")).to_have_text(re.compile(
        rf"^Faite par « {re.escape(principale['titre'])} » — fait lors du tour de retours du 25/09 "
        rf"\(commentaire de l'assistant, {QUAND}\)$"))


def test_une_tache_dont_l_agent_travaille_ne_se_classe_pas(bz_page):
    c = creer_chantier()
    t = creer_tache(uid("Longue"), "[scn:slow]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre(lambda: (ligne(t["id"]) or {}).get("agent_actif"), 60, message="l'agent ne travaille pas")
    ouvrir_bureau(bz_page)

    entree = _menu(bz_page, t["id"], "Marquer faite…")

    expect(entree).to_be_disabled()
    expect(entree).to_have_attribute("title", re.compile("arrête-le ou attends sa livraison"))
    refus = api("POST", f"/api/micros/{t['id']}/classer", {"motif": "caduque", "commentaire": "x"}, attendu=409)
    assert refus["error"]["code"] == "agent_actif"  # forme unique des erreurs (spec §9)
    api("POST", f"/api/micros/{t['id']}/arreter", {})
