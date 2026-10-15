# [desc] Bureau — tâches (U3) : créer (le texte va dans le brief), brief enregistré automatiquement (erreur → nouvel essai, rien de perdu), dépôt, « Déplacer vers… », décision laissée par un agent (noter ma décision), abandonner, rouvrir, recherche, archives. [/desc]
"""Parcours U3 de SPEC.md sur de vraies tâches du bac à sable."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_OK, Retenue, api, bz_browser, bz_page, creer_chantier, creer_tache, ligne,
    deplier, ouvrir_archives, ouvrir_bureau, section_loc, section_statut, simuler_erreur, tache_loc, uid,
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
    "services/work/taches_actions.py",
    "services/work/bureau_lignes.py",
    "services/work/taches_vue.py",
)]


def test_ajouter_une_tache_d_une_ligne(bz_page):
    """Entrée crée : champ verrouillé pendant l'appel, puis la tâche apparaît DÉPLIÉE, surlignée,
    focus dans le brief ; le champ d'ajout est vidé."""
    c = creer_chantier()
    ouvrir_bureau(bz_page, "chantier")
    zone = section_loc(bz_page, c["id"]).locator(".bz-add__input")
    titre = uid("Nouvelle tâche")
    zone.fill(titre)
    retenue = Retenue(bz_page, "**/api/micros", methode="POST")
    zone.press("Enter")
    retenue.attendre()
    expect(zone).to_have_attribute("aria-busy", "true")
    zone.press("Enter")  # R5 : ignorée
    retenue.relacher()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche créée")).to_be_visible(timeout=10000)
    tache = section_loc(bz_page, c["id"]).locator(".bz-task").filter(has_text=titre)
    expect(tache).to_have_count(1, timeout=10000)
    expect(tache.locator(".bz-task__titre")).to_have_attribute("aria-expanded", "true")
    expect(tache.locator(".bz-ed__brief")).to_be_focused()
    expect(zone).to_have_value("")
    micros = [m for m in api("GET", f"/api/micros?macro_id={c['id']}")["micros"] if m["titre"] == titre]
    assert len(micros) == 1


def test_ajouter_une_tache_multi_ligne_va_dans_le_brief(bz_page):
    """Un seul champ : tout le texte tapé part dans le brief ; la 1re ligne sert de libellé."""
    c = creer_chantier()
    ouvrir_bureau(bz_page, "chantier")
    zone = section_loc(bz_page, c["id"]).locator(".bz-add__input")
    titre = uid("Titre")
    zone.fill(titre)
    zone.press("Shift+Enter")
    zone.type("Le brief détaillé.")
    zone.press("Enter")
    tache = section_loc(bz_page, c["id"]).locator(".bz-task").filter(has_text=titre)
    expect(tache).to_have_count(1, timeout=10000)
    expect(tache.locator(".bz-task__titre")).to_have_text(titre)
    expect(tache.locator(".bz-ed__titre")).to_have_count(0)
    expect(tache.locator(".bz-ed__brief")).to_have_value(f"{titre}\nLe brief détaillé.")

def test_mode_statut_ajouter_une_tache_dans_a_lancer_avec_choix_du_chantier(bz_page):
    """Mode Statut : la zone d'ajout de « À lancer » a une liste « Chantier » ; la tâche créée y
    apparaît avec l'étiquette de son chantier, dépliée, focus dans le brief."""
    c = creer_chantier()
    ouvrir_bureau(bz_page)
    section = section_statut(bz_page, "a_lancer")
    section.locator(".bz-add__chantier").select_option(c["id"])
    zone = section.locator(".bz-add__input")
    titre = uid("Depuis Statut")
    zone.fill(titre)
    zone.press("Enter")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche créée")).to_be_visible(timeout=10000)
    tache = section.locator(".bz-task").filter(has_text=titre)
    expect(tache).to_have_count(1, timeout=10000)
    expect(tache.locator(".bz-task__chantier")).to_have_text(c["titre"])
    expect(tache.locator(".bz-ed__brief")).to_be_focused()
    assert [m for m in api("GET", f"/api/micros?macro_id={c['id']}")["micros"] if m["titre"] == titre]


def test_creation_en_erreur_garde_le_texte(bz_page):
    c = creer_chantier()
    ouvrir_bureau(bz_page, "chantier")
    simuler_erreur(bz_page, "**/api/micros", 500, methode="POST")
    zone = section_loc(bz_page, c["id"]).locator(".bz-add__input")
    zone.fill("Ne pas perdre ce texte")
    zone.press("Enter")
    expect(section_loc(bz_page, c["id"]).locator(".bz-add .field__error")).to_contain_text("Création impossible",
                                                                                          timeout=10000)
    expect(zone).to_have_value("Ne pas perdre ce texte")
    zone.press("Enter")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche créée")).to_be_visible(timeout=10000)


def test_le_brief_s_enregistre_tout_seul(bz_page):
    """Autosave : pas de bouton Enregistrer ; « Enregistrement… » puis « Enregistré » ; la 1re ligne
    devient le libellé ; un rafraîchissement pendant la frappe n'écrase rien ; le texte survit au
    rechargement."""
    c = creer_chantier()
    t = creer_tache(corps="brief initial", macro_id=c["id"])
    ouvrir_bureau(bz_page)
    tache = deplier(bz_page, t["id"])
    expect(tache.get_by_role("button", name="Enregistrer")).to_have_count(0)
    brief = tache.locator(".bz-ed__brief")
    nouveau = uid("Nouveau libellé")
    retenue = Retenue(bz_page, f"**/api/micros/{t['id']}", methode="PATCH")
    brief.fill(f"{nouveau}\nle détail")
    bz_page.evaluate("window.dispatchEvent(new CustomEvent('bz:render'))")
    retenue.attendre(delai_ms=5000)
    expect(tache.locator(".bz-ed__etat")).to_have_text("Enregistrement…")
    expect(brief).to_have_value(f"{nouveau}\nle détail")
    retenue.relacher()
    expect(tache.locator(".bz-ed__etat")).to_have_text("Enregistré", timeout=10000)
    expect(tache.locator(".bz-task__titre")).to_have_text(nouveau)
    m = ligne(t["id"])
    assert m["titre"] == nouveau and m["corps"] == f"{nouveau}\nle détail"
    brief.fill(f"{nouveau}\nvia la perte de focus")
    brief.blur()
    expect(tache.locator(".bz-ed__etat")).to_have_text("Enregistré", timeout=10000)
    bz_page.reload()
    expect(tache_loc(bz_page, t["id"]).locator(".bz-ed__brief")).to_have_value(f"{nouveau}\nvia la perte de focus",
                                                                                 timeout=15000)

def test_erreur_d_enregistrement_garde_le_texte_et_reessaie(bz_page):
    """Erreur serveur simulée : message à côté du brief, texte intact, nouvel essai automatique."""
    t = creer_tache(corps="b")
    ouvrir_bureau(bz_page)
    tache = deplier(bz_page, t["id"])
    simuler_erreur(bz_page, f"**/api/micros/{t['id']}", 500, methode="PATCH")
    brief = tache.locator(".bz-ed__brief")
    brief.fill("Ne pas perdre ce texte")
    etat = tache.locator(".bz-ed__etat")
    expect(etat).to_contain_text("Pas encore enregistré", timeout=10000)
    expect(etat).to_have_attribute("data-erreur", "true")
    expect(brief).to_have_value("Ne pas perdre ce texte")
    expect(etat).to_have_text("Enregistré", timeout=15000)
    assert ligne(t["id"])["corps"] == "Ne pas perdre ce texte"

def test_changer_de_depot_et_deplacer_via_le_menu(bz_page):
    """Dépôt : liste à effet immédiat. Chantier : pas de sélecteur visible ; « Déplacer vers… »
    dans le menu ⋯ (alternative clavier au glisser-déposer)."""
    a = creer_chantier(uid("Source"))
    b = creer_chantier(uid("Cible"))
    t = creer_tache(uid("Mobile"), macro_id=a["id"])
    ouvrir_bureau(bz_page, "chantier")
    tache = deplier(bz_page, t["id"])
    expect(tache.get_by_label("Chantier", exact=True)).to_have_count(0)
    tache.get_by_label("Dépôt", exact=True).select_option("demo-data")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Dépôt : demo-data")).to_be_visible(timeout=10000)
    assert ligne(t["id"])["projet_slug"] == "demo-data"
    tache.get_by_role("button", name="Autres actions sur la tâche").click()
    bz_page.get_by_role("menuitem", name="Déplacer vers…").click()
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    expect(dlg).to_contain_text("Déplacer vers")
    dlg.get_by_role("button", name=b["titre"]).click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche déplacée")).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, b["id"]).locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1, timeout=10000)
    assert ligne(t["id"])["macro_id"] == b["id"]

def test_decision_laissee_par_un_agent_noter_ma_decision_puis_rouvrir(bz_page):
    """Une décision (créée par un agent, `decision: true`) est sous « Décider », dite « Décision »,
    avec « aucun agent n'attend » ; « Noter ma décision… » l'ajoute au brief et clôt la tâche ;
    elle est alors dans Archivées, et Rouvrir la ramène."""
    r = api("POST", "/api/micros", {"corps": uid("Décision"), "decision": True}, attendu=201)
    t = r["micro"]
    ouvrir_bureau(bz_page)
    tache = bz_page.locator(".bz-cat[data-cat='decider']").locator(f".bz-task[data-id='{t['id']}']")
    expect(tache).to_have_attribute("data-motif", "point", timeout=10000)
    expect(tache.locator(".bz-task__badge")).to_contain_text("À décider")
    expect(tache.locator(".bz-task__meta")).to_contain_text("Aucun agent n'attend")
    b = tache.locator(".bz-task__attente")
    b.get_by_role("button", name="Noter ma décision…").click()
    champ = tache.get_by_label("Ta décision")
    expect(champ).to_be_focused()
    champ.fill("On garde le point-virgule.")
    tache.get_by_role("button", name="Noter et clore").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Décision notée — tâche close")).to_be_visible(timeout=10000)
    assert ligne(t["id"])["statut_ui"] == "faite"
    micro = api("GET", f"/api/micros/{t['id']}")
    micro = micro.get("micro", micro)
    assert any("On garde le point-virgule." in p["texte"] for p in micro.get("precisions") or []), micro
    ouvrir_archives(bz_page)
    tache = section_statut(bz_page, "archivees").locator(f".bz-task[data-id='{t['id']}']")
    expect(tache).to_have_attribute("data-statut", "faite", timeout=10000)
    deplier(bz_page, t["id"])
    tache.get_by_role("button", name="Rouvrir").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="rouverte")).to_be_visible(timeout=10000)
    assert ligne(t["id"])["statut_ui"] in ("brouillon", "a_decider")

def test_abandonner_puis_rouvrir_depuis_le_toast(bz_page):
    t = creer_tache(uid("À abandonner"))
    ouvrir_bureau(bz_page, "a_lancer")
    deplier(bz_page, t["id"])
    tache_loc(bz_page, t["id"]).get_by_role("button", name="Abandonner", exact=True).click()
    toast = bz_page.locator(TOAST_OK).filter(has_text="Tâche abandonnée")
    expect(toast).to_be_visible(timeout=10000)
    expect(tache_loc(bz_page, t["id"])).to_have_count(0, timeout=10000)
    toast.get_by_role("button", name="Annuler").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="rouverte")).to_be_visible(timeout=10000)
    expect(section_statut(bz_page, "a_lancer").locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1, timeout=10000)


def test_recherche_filtre_les_deux_modes(bz_page):
    """La recherche (titre + brief, sans accents ni casse) filtre pareil en mode Statut et en mode
    Chantier ; rien trouvé → un seul message."""
    t = creer_tache(uid("Aiguille unique"))
    ouvrir_bureau(bz_page)
    bz_page.locator("#bz-search").fill(t["titre"].upper())
    expect(bz_page.locator("#lignes-liste .bz-task")).to_have_count(1, timeout=5000)
    expect(tache_loc(bz_page, t["id"])).to_be_visible()
    choisir = bz_page.locator("#bz-mode [data-mode='chantier']")
    choisir.click()
    expect(bz_page.locator("#lignes-liste .bz-task")).to_have_count(1, timeout=5000)
    expect(tache_loc(bz_page, t["id"])).to_be_visible()
    bz_page.locator("#bz-search").fill("zzz-introuvable")
    expect(bz_page.locator("#lignes-liste .empty")).to_contain_text("Aucune tâche pour « zzz-introuvable »", timeout=5000)


def test_mode_chantier_archivees_repliees_en_bas_du_chantier(bz_page):
    """Mode Chantier : les tâches archivées d'un chantier sont repliées en bas (« ▸ N archivée ») ;
    un clic les montre."""
    c = creer_chantier()
    t = creer_tache(uid("Archivée"), macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/etat", {"etat": "faite"}, attendu=200)
    ouvrir_bureau(bz_page, "chantier")
    section = section_loc(bz_page, c["id"])
    bouton = section.locator(".bz-arch__btn")
    expect(bouton).to_contain_text("1 archivée", timeout=10000)
    expect(section.locator(f".bz-task[data-id='{t['id']}']")).to_have_count(0)
    bouton.click()
    expect(section.locator(f".bz-arch__corps .bz-task[data-id='{t['id']}']")).to_have_count(1)
