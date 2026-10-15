# [desc] Bureau — arrivée sur l'accueil (U1), deux modes de tri (Statut | Chantier) mémorisés, bouton flottant de l'assistant, connexion perdue (U15), clavier et hygiène (U16). [/desc]
"""Parcours U1, U15, U16 de SPEC.md sur la page Bureau."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401 — fixtures importées pour pytest
    BASE, DEPOT, MARQUES, Retenue, api, attendre, attendre_statut, bz_browser, bz_page, choisir_mode,
    creer_chantier, creer_tache, ouvrir_bureau, simuler_erreur, uid,
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
    "routes/work/inbox.py",
    "services/work/inbox.py",
    "services/work/bureau_lignes.py",
    "services/work/taches_vue.py",
    "routes/work/tasks.py",
    "app.py",
)]


def test_la_racine_amene_au_bureau_avec_un_squelette_puis_le_contenu(bz_page):
    """U1 : `/` → `/bureau` ; tant que /api/lignes n'a pas répondu, un squelette tient la place (R2)."""
    retenue = Retenue(bz_page, "**/api/lignes")
    bz_page.goto(f"{BASE}/")
    expect(bz_page).to_have_url(re.compile(r"/bureau$"))
    retenue.attendre()
    expect(bz_page.locator("#lignes-liste .skeleton")).to_be_visible()
    expect(bz_page.locator("#lignes-liste")).to_have_attribute("aria-busy", "true")
    retenue.relacher()
    expect(bz_page.locator("#lignes-liste .skeleton")).to_have_count(0, timeout=15000)
    expect(bz_page.locator("#bz-mode .seg__btn")).to_have_count(2)
    expect(bz_page.locator("#bz-mode [data-mode='statut']")).to_have_attribute("aria-pressed", "true")
    expect(bz_page.locator(".bz-sec[data-sec='a_moi'] .bz-sec__titre")).to_contain_text("À traiter")
    expect(bz_page).to_have_title(re.compile(r"Bureau"))


def _compte_du_titre(page) -> int:
    m = re.match(r"^\((\d+)\) Bureau", page.title())
    return int(m.group(1)) if m else 0


def test_le_titre_de_l_onglet_compte_ce_qui_m_attend(bz_page):
    """R12 : « (N) Bureau — bouzecode » quand des points attendent l'utilisateur.

    Étanche : le bac est partagé (test_contraste_e2e.py y crée des agents en même temps), donc
    on ne compare pas le titre à un total global. On lit le compteur, on crée SON point à
    traiter (une tâche rendue, « à vérifier »), puis on attend que le titre compte au moins
    `avant + 1` : l'ajout d'un point par un autre test ne peut que l'augmenter."""
    ouvrir_bureau(bz_page)
    avant = api("GET", "/api/nav/counts").get("a_moi") or 0
    chantier = creer_chantier()
    tache = creer_tache(uid("Titre"), "Livrer.\n[scn:recap]", macro_id=chantier["id"])
    api("POST", f"/api/micros/{tache['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(tache["id"], "a_relire", delai=120)
    vu = [""]

    def compte_au_moins_un_de_plus():
        vu[0] = bz_page.title()
        return _compte_du_titre(bz_page) >= avant + 1

    try:
        attendre(compte_au_moins_un_de_plus, delai=30)
    except AssertionError:
        raise AssertionError(f"titre « ({avant + 1} ou plus) Bureau » attendu, vu {vu[0]!r}") from None
    expect(bz_page).to_have_title(re.compile(r"^\(\d+\) Bureau"))


def test_une_erreur_de_chargement_propose_de_reessayer(bz_page):
    """R4 : /api/lignes en 500 → état d'erreur avec « Réessayer », qui recharge vraiment."""
    simuler_erreur(bz_page, "**/api/lignes")
    bz_page.goto(f"{BASE}/bureau")
    erreur = bz_page.locator("#lignes-liste .error-state")
    expect(erreur).to_be_visible(timeout=15000)
    expect(erreur).to_contain_text("Impossible de charger tes tâches")
    erreur.get_by_role("button", name="Réessayer").click()
    expect(bz_page.locator("#lignes-liste .error-state")).to_have_count(0, timeout=15000)
    expect(bz_page.locator("#lignes-liste .bz-sec, #lignes-liste .empty").first).to_be_visible()


def test_connexion_perdue_puis_retrouvee(bz_page):
    """U15 / R7 : deux échecs réseau consécutifs lèvent le bandeau ; « Réessayer maintenant »
    le fait disparaître dès que le serveur répond, et le texte saisi n'est pas perdu (R4)."""
    ouvrir_bureau(bz_page, "chantier")
    bz_page.route("**/api/**", lambda route: route.abort("connectionrefused"))
    bz_page.erreurs_attendues += ["Failed to load resource", "ERR_CONNECTION_REFUSED"]
    champ = bz_page.locator("#chantier-titre")
    champ.fill("Chantier hors ligne")
    champ.press("Enter")
    expect(bz_page.locator("#chantier-erreur")).to_contain_text("Serveur injoignable", timeout=10000)
    champ.press("Enter")
    banniere = bz_page.locator("#offline-banner")
    expect(banniere).to_be_visible(timeout=10000)
    expect(banniere).to_contain_text("Connexion au serveur perdue")
    expect(champ).to_have_value("Chantier hors ligne")
    bz_page.unroute("**/api/**")
    banniere.get_by_role("button", name="Réessayer maintenant").click()
    expect(banniere).to_be_hidden(timeout=10000)


def test_navigation_au_clavier(bz_page):
    """U16 / R10 : « / » va à la recherche, Échap la vide ; Ctrl+J ouvre l'assistant, Échap le ferme ;
    une tâche se déplie au clavier (Entrée) sans souris."""
    ouvrir_bureau(bz_page, "a_lancer")
    bz_page.locator("body").press("/")
    expect(bz_page.locator("#bz-search")).to_be_focused()
    bz_page.keyboard.type("zzz-introuvable")
    expect(bz_page.locator("#lignes-liste .empty")).to_contain_text("Aucune tâche pour", timeout=5000)
    bz_page.keyboard.press("Escape")
    expect(bz_page.locator("#bz-search")).to_have_value("")
    bz_page.keyboard.press("Control+j")
    expect(bz_page.locator("#assistant-drawer")).to_have_attribute("data-open", "true")
    expect(bz_page.locator("#assistant-input")).to_be_focused()
    bz_page.keyboard.press("Escape")
    expect(bz_page.locator("#assistant-drawer")).to_have_attribute("data-open", "false")
    ligne = bz_page.locator("button.bz-task__titre").first
    if ligne.count():
        ligne.focus()
        bz_page.keyboard.press("Enter")
        expect(ligne).to_have_attribute("aria-expanded", "true")
        bz_page.keyboard.press("Enter")
        expect(ligne).to_have_attribute("aria-expanded", "false")


def test_les_deux_modes_se_basculent_et_se_souviennent_du_choix(bz_page):
    """« Trier par : Statut | Chantier » : une seule vue à la fois ; le mode choisi survit au
    rechargement ; au clavier, les flèches passent d'un mode à l'autre."""
    ouvrir_bureau(bz_page)
    expect(bz_page.locator(".bz-sec[data-sec='a_lancer']")).to_be_visible()
    expect(bz_page.locator(".bz-ch")).to_have_count(0)
    expect(bz_page.locator("#chantier-nouveau")).to_be_hidden()
    choisir_mode(bz_page, "chantier")
    expect(bz_page.locator(".bz-ch").first).to_be_visible()
    expect(bz_page.locator(".bz-sec[data-sec='a_lancer']")).to_have_count(0)
    expect(bz_page.locator("#chantier-nouveau")).to_be_visible()
    bz_page.reload()
    expect(bz_page.locator("#bz-mode [data-mode='chantier']")).to_have_attribute("aria-pressed", "true", timeout=15000)
    expect(bz_page.locator(".bz-ch").first).to_be_visible(timeout=15000)
    bz_page.locator("#bz-mode [data-mode='chantier']").focus()
    bz_page.keyboard.press("ArrowLeft")
    expect(bz_page.locator("#bz-mode [data-mode='statut']")).to_have_attribute("aria-pressed", "true")
    expect(bz_page.locator("#bz-mode [data-mode='statut']")).to_be_focused()


def test_aucune_tache_n_apparait_deux_fois(bz_page):
    """Dans chaque mode, chaque tâche (et chaque point hors tâche) n'apparaît qu'une fois."""
    ouvrir_bureau(bz_page)
    for mode in ("statut", "chantier"):
        choisir_mode(bz_page, mode)
        ids = bz_page.eval_on_selector_all("#lignes-liste .bz-task", "els => els.map(e => e.dataset.id)")
        assert ids, f"aucune tâche en mode {mode}"
        assert len(ids) == len(set(ids)), f"doublons en mode {mode} : {sorted(i for i in ids if ids.count(i) > 1)}"


def test_le_bouton_flottant_ouvre_l_assistant(bz_page):
    """Bouton flottant en bas à droite (« Ouvrir l'assistant ») ; il ne masque aucun contenu
    (marge basse), disparaît tiroir ouvert et reprend le focus à la fermeture."""
    ouvrir_bureau(bz_page)
    bulle = bz_page.get_by_role("button", name="Ouvrir l'assistant")
    expect(bulle).to_be_visible()
    boite = bulle.bounding_box()
    vue = bz_page.viewport_size
    assert boite["x"] + boite["width"] > vue["width"] - 60 and boite["y"] + boite["height"] > vue["height"] - 60
    bz_page.keyboard.press("End")
    bz_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    derniere = bz_page.locator("#lignes-liste .bz-task").last
    b2 = derniere.bounding_box()
    assert b2["y"] + b2["height"] <= boite["y"] or b2["x"] + b2["width"] <= boite["x"], "la bulle masque la dernière tâche"
    bulle.click()
    expect(bz_page.locator("#assistant-drawer")).to_have_attribute("data-open", "true")
    expect(bz_page.locator("#assistant-bulle")).to_be_hidden()
    bz_page.keyboard.press("Escape")
    expect(bz_page.locator("#assistant-bulle")).to_be_focused()
