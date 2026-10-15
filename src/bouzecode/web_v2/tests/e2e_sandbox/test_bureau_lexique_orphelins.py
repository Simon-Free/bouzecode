# [desc] Bureau — lexique unique et tâches orphelines (TODO §6) : mêmes mots que le serveur sur les badges et les compteurs, « À lancer » non répété dans sa section, section « Sans chantier » qui dit ce qu'elle contient et comment ranger une tâche. [/desc]
"""TODO §6 de l'utilisateur : « la gestion des tickets est ingérable… vue kanban à remettre à plat
(états, regroupement par chantier, tickets orphelins) ». Ce que ce fichier vérifie dans le vrai
navigateur, contre le bac à sable :

* les mots affichés sont ceux de la table serveur (`/api/lexique`, injectée dans la page) ;
* « À lancer » n'est pas répété sur chaque ligne de la section « À lancer » (icône seule) ;
* les compteurs d'un chantier parlent le même lexique que les badges ;
* la section « Sans chantier » dit ce qu'elle contient et le geste qui range une tâche, et ce
  geste (poignée → « Déplacer vers… ») la sort de la section.
"""
from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    MARQUES, TOAST_OK, api, bz_browser, bz_page, creer_chantier, creer_tache, ligne, ouvrir_bureau,
    section_loc, section_statut, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/base.html", "app.py", "services/work/lexique.py", "static/js/lib/states.js",
    "static/js/bureau/**", "static/css/bureau.css", "services/work/taches_vue.py",
)]


def test_la_page_porte_le_lexique_du_serveur(bz_page):
    ouvrir_bureau(bz_page)
    injecte = json.loads(bz_page.locator("#bz-lexique").text_content())
    assert injecte == api("GET", "/api/lexique")
    assert injecte["entrees"]["brouillon"]["mot"] == "À lancer"


def test_badges_et_compteurs_disent_les_memes_mots(bz_page):
    chantier = creer_chantier(uid("Lexique"))
    brouillon = creer_tache(uid("À écrire"), macro_id=chantier["id"])
    decision = api("POST", "/api/micros", {"corps": uid("Garder le JSON ?"), "decision": True,
                                            "macro_id": chantier["id"]}, attendu=201)["micro"]
    ouvrir_bureau(bz_page)
    #  Mode Statut : la section « À lancer » ne répète pas « À lancer » sur ses lignes.
    badge = section_statut(bz_page, "a_lancer").locator(f".bz-task[data-id='{brouillon['id']}'] .badge")
    expect(badge).to_have_attribute("title", "À lancer")
    expect(badge).to_have_class(re.compile(r"\bbadge--compact\b"))  # mot réservé à l'infobulle
    expect(tache_loc(bz_page, decision["id"]).locator(".bz-task__badge")).to_contain_text("À décider")
    #  Mode Chantier : les compteurs de l'en-tête, avec les mêmes mots.
    ouvrir_bureau(bz_page, "chantier")
    comptes = section_loc(bz_page, chantier["id"]).locator(".bz-ch__comptes")
    expect(comptes).to_have_text("1 à décider · 1 à lancer")
    expect(tache_loc(bz_page, brouillon["id"]).locator(".bz-task__badge")).to_contain_text("À lancer")
    bz_page.screenshot(path=_capture("apres_bureau_chantier_lexique.png"), full_page=True)


def test_sans_chantier_dit_ce_qu_elle_contient_et_comment_ranger(bz_page):
    chantier = creer_chantier(uid("Destination"))
    orpheline = creer_tache(uid("Orpheline"))
    ouvrir_bureau(bz_page, "chantier")
    sans = bz_page.locator(".bz-ch[data-chantier='sans']")
    expect(sans.locator(".bz-ch__aide")).to_be_visible()
    expect(sans.locator(".bz-ch__aide")).to_contain_text("Rattachées à aucun chantier")
    expect(sans.locator(f".bz-task[data-id='{orpheline['id']}']")).to_have_count(1)
    bz_page.screenshot(path=_capture("apres_bureau_sans_chantier.png"), full_page=True)

    tache_loc(bz_page, orpheline["id"]).get_by_role("button", name="Déplacer la tâche vers un autre chantier").click()
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    dlg.get_by_role("button", name=chantier["titre"], exact=True).click()
    expect(bz_page.locator(TOAST_OK).filter(has_text=f"Tâche déplacée dans « {chantier['titre']} »")).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, chantier["id"]).locator(f".bz-task[data-id='{orpheline['id']}']")).to_have_count(1)
    expect(sans.locator(f".bz-task[data-id='{orpheline['id']}']")).to_have_count(0)
    assert ligne(orpheline["id"])["macro_id"] == chantier["id"]


def _capture(nom: str) -> str | None:
    """Capture d'écran pour le compte rendu si `BZ_E2E_CAPTURES` est posé (sinon aucune écriture)."""
    import os
    dossier = os.environ.get("BZ_E2E_CAPTURES")
    return os.path.join(dossier, nom) if dossier else None
