# [desc] Bureau — dialogue Lancer : choix Local / Rundeck, mode Tests (commande exigée avant tout appel), fichiers non suivis lus sur le vrai serveur, refus Rundeck dit dans le dialogue, lancement local ordinaire. [/desc]
"""Bac à sable (HOME jetable, faux LLM). Aucun job Rundeck n'est jamais soumis : le POST Rundeck est
intercepté dans le navigateur et reçoit le refus que rendrait un serveur sans lanceur distant."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_OK, bz_browser, bz_page, creer_chantier, creer_tache, ouvrir_bureau,
    simuler_erreur, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "static/js/bureau/lancer*.js", "static/js/bureau/actions.js", "static/js/bureau/passages.js",
    "static/css/bureau.css", "routes/work/projects.py", "services/work/projets_etat.py",
    "services/work/taches_execution.py",
)]


def _dialogue(page, t):
    tache = tache_loc(page, t["id"])
    tache.locator(".bz-task__titre").click()
    tache.locator(".bz-task__actions").get_by_role("button", name="Lancer", exact=True).click()
    dlg = page.locator("dialog.bz-launch[open]")
    expect(dlg).to_be_visible()
    dlg.get_by_label("Dépôt").select_option(DEPOT)
    return dlg


def test_rundeck_mode_tests_puis_refus_dit_dans_le_dialogue(bz_page):
    c = creer_chantier()
    t = creer_tache(uid("Exécution"), "Jouer les tests.\n[scn:reply]", macro_id=c["id"])
    ouvrir_bureau(bz_page, "a_lancer")
    dlg = _dialogue(bz_page, t)
    execution = dlg.locator("[data-role=execution]")
    expect(execution.get_by_label("Sur ce poste (local)")).to_be_checked()
    expect(execution.locator("[data-role=rundeck]")).to_be_hidden()
    execution.locator("summary", has_text="Fichiers non suivis").click()
    expect(execution.locator("[data-role=fichiers-etat]")).not_to_contain_text("Lecture", timeout=10000)

    execution.get_by_label("Sur Rundeck — VM Linux de recette").check()
    execution.get_by_label("Tests seulement", exact=False).check()
    appels = []
    bz_page.on("request", lambda r: "/lancer" in r.url and appels.append(r.url))
    dlg.locator("[data-role=go]").click()
    expect(execution.locator("[data-role=commande]")).to_be_focused()
    expect(execution).to_contain_text("Donne les arguments de pytest")
    assert appels == []

    simuler_erreur(bz_page, f"**/api/micros/{t['id']}/lancer", 501, methode="POST", corps={
        "error": {"code": "cible_indisponible", "message": "L'execution sur rundeck n'est pas disponible"}})
    execution.locator("[data-role=commande]").fill("tests -x")
    dlg.locator("[data-role=go]").click()
    erreur = dlg.locator(".bz-launch__erreur")
    expect(erreur).to_contain_text("pas disponible", timeout=10000)
    expect(erreur).to_contain_text("Sur ce poste")
    expect(dlg.locator("[data-role=go]")).to_be_enabled()

    execution.get_by_label("Sur ce poste (local)").check()
    dlg.locator("[data-role=go]").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Agent lancé")).to_be_visible(timeout=30000)
    expect(bz_page.locator("dialog.bz-launch[open]")).to_have_count(0)
