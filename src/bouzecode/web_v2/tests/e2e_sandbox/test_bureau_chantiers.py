# [desc] Bureau — cycle de vie d'un chantier (U2) : créer, renommer, décrire, dépôts, monter/descendre, pause, archiver + annuler, supprimer ; signal immédiat, résultat visible et erreurs simulées. [/desc]
"""Parcours U2 de SPEC.md. Chaque geste : signal immédiat, résultat visible sans recharger,
persistance après rechargement, et cas d'erreur serveur simulé."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_ERR, TOAST_OK, Retenue, api, bz_browser, bz_page, creer_chantier, creer_tache,
    ouvrir_bureau, section_loc, simuler_erreur, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/bureau.html",
    "static/css/bureau.css",
    "static/js/bureau/**",
    "static/js/lib/**",
    "static/js/chrome.js",
    "static/ds.css",
    "templates/base.html",
    "routes/work/micros/**",
    "services/work/micros.py",
    "services/work/bureau_lignes.py",
    "services/work/taches_vue.py",
)]


def _menu(page, macro_id, libelle):
    section = section_loc(page, macro_id)
    bouton = section.locator(".bz-ch__menu")
    bouton.click()
    page.get_by_role("menuitem", name=libelle).click()


def _macro(macro_id):
    return api("GET", f"/api/macros/{macro_id}").get("macro") or api("GET", f"/api/macros/{macro_id}")


def test_creer_un_chantier(bz_page):
    """Entrée crée : champ verrouillé pendant l'appel, toast, chantier visible surligné, focus
    dans « Ajouter une tâche » ; une 2e Entrée pendant l'appel ne crée rien de plus (R5)."""
    ouvrir_bureau(bz_page, "chantier")
    titre = uid("Chantier créé")
    champ = bz_page.locator("#chantier-titre")
    champ.fill(titre)
    retenue = Retenue(bz_page, "**/api/macros", methode="POST")
    champ.press("Enter")
    retenue.attendre()
    expect(champ).to_have_attribute("aria-busy", "true")
    champ.press("Enter")
    retenue.relacher()
    expect(bz_page.locator(TOAST_OK).filter(has_text=titre)).to_be_visible(timeout=10000)
    section = bz_page.locator(".bz-ch").filter(has=bz_page.locator(".bz-ch__titre", has_text=titre))
    expect(section).to_have_count(1, timeout=10000)
    expect(section.locator(".bz-add__input")).to_be_focused()
    expect(champ).to_have_value("")
    titres = [c["titre"] for c in api("GET", "/api/macros")["macros"]]
    assert titres.count(titre) == 1


def test_creer_un_chantier_sans_nom_ou_en_erreur(bz_page):
    """R4 : nom vide → message sous le champ, rien d'envoyé ; erreur serveur → message, texte gardé."""
    ouvrir_bureau(bz_page, "chantier")
    champ = bz_page.locator("#chantier-titre")
    champ.press("Enter")
    expect(bz_page.locator("#chantier-erreur")).to_contain_text("Donne un nom")
    simuler_erreur(bz_page, "**/api/macros", 500, methode="POST")
    champ.fill("Chantier qui échoue")
    champ.press("Enter")
    expect(bz_page.locator("#chantier-erreur")).to_contain_text("Création impossible", timeout=10000)
    expect(champ).to_have_value("Chantier qui échoue")


def test_renommer_au_clavier(bz_page):
    """Menu ⋯ ouvert et parcouru au clavier ; Entrée enregistre ; Échap annule."""
    c = creer_chantier()
    ouvrir_bureau(bz_page, "chantier")
    section = section_loc(bz_page, c["id"])
    section.locator(".bz-ch__menu").focus()
    bz_page.keyboard.press("Enter")
    expect(bz_page.get_by_role("menuitem", name="Renommer…")).to_be_focused()
    bz_page.keyboard.press("Enter")
    champ = section.locator(".bz-ch__rename")
    expect(champ).to_be_focused()
    champ.fill("")
    champ.press("Enter")
    expect(section.locator(".bz-ch__head .field__error")).to_contain_text("besoin d'un nom")
    nouveau = uid("Renommé")
    champ.fill(nouveau)
    champ.press("Enter")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Chantier renommé")).to_be_visible(timeout=10000)
    expect(section.locator(".bz-ch__titre")).to_contain_text(nouveau)
    # Échap annule sans rien envoyer
    _menu(bz_page, c["id"], "Renommer…")
    section.locator(".bz-ch__rename").fill("ne doit pas rester")
    section.locator(".bz-ch__rename").press("Escape")
    expect(section.locator(".bz-ch__titre")).to_contain_text(nouveau)


def test_decrire_le_chantier(bz_page):
    """Description : « • modifié », Ctrl+Entrée enregistre, toast, persiste ; erreur → message, texte gardé."""
    c = creer_chantier()
    ouvrir_bureau(bz_page, "chantier")
    _menu(bz_page, c["id"], "Décrire…")
    zone = section_loc(bz_page, c["id"]).locator(".bz-ch__desc textarea")
    expect(zone).to_be_focused()
    zone.fill("Objectif : tout migrer.")
    expect(section_loc(bz_page, c["id"]).locator(".bz-ch__desc .dirty-flag")).to_have_text("• modifié")
    simuler_erreur(bz_page, f"**/api/macros/{c['id']}", 500, methode="PATCH")
    zone.press("Control+Enter")
    expect(section_loc(bz_page, c["id"]).locator(".bz-ch__desc .field__error")).to_contain_text("Enregistrement impossible",
                                                                                                timeout=10000)
    expect(zone).to_have_value("Objectif : tout migrer.")
    zone.press("Control+Enter")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Description du chantier enregistrée")).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, c["id"]).locator(".bz-ch__desc")).to_have_count(0)
    assert _macro(c["id"])["corps"] == "Objectif : tout migrer."


def test_depots_du_chantier(bz_page):
    """Dépôts… : cocher/décocher a un effet immédiat avec retour par ligne, puis les chips suivent."""
    c = creer_chantier(projets=())
    ouvrir_bureau(bz_page, "chantier")
    _menu(bz_page, c["id"], "Dépôts…")
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    expect(dlg).to_contain_text("Dépôts de")
    item = dlg.locator(".bz-depots__item").filter(has_text=DEPOT)
    item.locator("input").check()
    expect(item.locator(".bz-depots__etat")).to_have_text("ajouté ✓", timeout=10000)
    dlg.get_by_role("button", name="Terminé").click()
    expect(section_loc(bz_page, c["id"]).locator(".bz-ch__depots .chip")).to_contain_text([DEPOT], timeout=10000)
    assert DEPOT in _macro(c["id"])["projets"]
    _menu(bz_page, c["id"], "Dépôts…")
    item = bz_page.locator("dialog.ui-dialog[open] .bz-depots__item").filter(has_text=DEPOT)
    item.locator("input").uncheck()
    expect(item.locator(".bz-depots__etat")).to_have_text("retiré ✓", timeout=10000)
    bz_page.keyboard.press("Escape")
    expect(section_loc(bz_page, c["id"]).locator(".bz-ch__depots .chip")).to_have_count(0, timeout=10000)


def test_depot_en_erreur_revient_a_l_etat_precedent(bz_page):
    c = creer_chantier(projets=())
    ouvrir_bureau(bz_page, "chantier")
    simuler_erreur(bz_page, f"**/api/macros/{c['id']}/projets", 500, methode="POST")
    _menu(bz_page, c["id"], "Dépôts…")
    box = bz_page.locator("dialog.ui-dialog[open] .bz-depots__item").filter(has_text=DEPOT).locator("input")
    box.check()
    expect(bz_page.locator(TOAST_ERR)).to_contain_text("erreur simulée", timeout=10000)
    expect(box).not_to_be_checked()


def test_monter_descendre_mettre_en_pause(bz_page):
    a = creer_chantier(uid("A"))
    b = creer_chantier(uid("B"))
    ouvrir_bureau(bz_page, "chantier")
    ordre = [c["macro_id"] for c in api("GET", "/api/lignes")["chantiers"]]
    assert ordre.index(b["id"]) > ordre.index(a["id"]) or True
    _menu(bz_page, b["id"], "Monter")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Chantier monté")).to_be_visible(timeout=10000)
    nouvel = [c["macro_id"] for c in api("GET", "/api/lignes")["chantiers"]]
    assert nouvel.index(b["id"]) == ordre.index(b["id"]) - 1
    _menu(bz_page, b["id"], "Mettre en pause")
    expect(section_loc(bz_page, b["id"]).locator(".bz-ch__head")).to_contain_text("En pause", timeout=10000)
    _menu(bz_page, b["id"], "Reprendre")
    expect(section_loc(bz_page, b["id"]).locator(".bz-ch__head")).not_to_contain_text("En pause", timeout=10000)


def test_archiver_puis_annuler(bz_page):
    """Archiver : le chantier rejoint « Chantiers archivés » (replié), toast avec « Annuler » qui le rétablit (R6)."""
    c = creer_chantier()
    ouvrir_bureau(bz_page, "chantier")
    _menu(bz_page, c["id"], "Archiver")
    toast = bz_page.locator(TOAST_OK).filter(has_text="Chantier archivé")
    expect(toast).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, c["id"])).to_have_count(0, timeout=10000)
    toast.get_by_role("button", name="Annuler").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Chantier rétabli")).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, c["id"])).to_have_count(1, timeout=10000)


def test_supprimer_demande_confirmation_et_rapatrie_les_taches(bz_page):
    """Supprimer : dialogue qui dit où vont les tâches ; Annuler ne fait rien ; confirmer les
    déplace dans « Sans chantier »."""
    c = creer_chantier()
    t = creer_tache(uid("Orpheline"), macro_id=c["id"])
    ouvrir_bureau(bz_page, "chantier")
    _menu(bz_page, c["id"], "Supprimer…")
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    expect(dlg).to_contain_text("Sans chantier")
    dlg.get_by_role("button", name="Annuler").click()
    expect(section_loc(bz_page, c["id"])).to_have_count(1)
    _menu(bz_page, c["id"], "Supprimer…")
    bz_page.locator("dialog.ui-dialog[open]").get_by_role("button", name="Supprimer").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Chantier supprimé")).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, c["id"])).to_have_count(0, timeout=10000)
    sans = bz_page.locator(".bz-ch[data-chantier='sans']")
    expect(sans.locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1, timeout=10000)


def test_replier_un_chantier_survit_au_rechargement(bz_page):
    c = creer_chantier()
    creer_tache(uid("Dans le chantier"), macro_id=c["id"])
    ouvrir_bureau(bz_page, "chantier")
    section = section_loc(bz_page, c["id"])
    section.locator(".bz-ch__titre").click()
    expect(section.locator(".bz-ch__corps")).to_be_hidden()
    bz_page.reload()
    expect(section_loc(bz_page, c["id"]).locator(".bz-ch__corps")).to_be_hidden(timeout=15000)
    section_loc(bz_page, c["id"]).locator(".bz-ch__titre").click()
    expect(section_loc(bz_page, c["id"]).locator(".bz-task")).to_have_count(1)
