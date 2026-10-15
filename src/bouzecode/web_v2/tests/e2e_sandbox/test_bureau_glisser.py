# [desc] Bureau — glisser-déposer (U3, U2) aux événements pointeur : liste longue avec défilement automatique, chantiers compactés pendant le geste, dépôt dans un chantier replié (qui s'entrouvre au survol), plateau de cibles en mode Statut, Échap pour annuler, réordonner un chantier avec indicateur d'insertion, alternatives clavier / menu, retour visuel et Annuler. [/desc]
"""Le glisser-déposer du Bureau, joué à la souris réelle de Playwright (pointerdown / move / up)."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    MARQUES, TOAST_INFO, TOAST_OK, Retenue, api, bz_browser, bz_page, choisir_mode, creer_chantier, creer_tache,
    ligne, ouvrir_bureau, section_loc, section_statut, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/bureau.html",
    "static/css/bureau.css",
    "static/js/bureau/**",
    "static/js/lib/**",
    "static/ds.css",
    "routes/work/micros/**",
    "services/work/micros.py",
)]


def _centre(loc):
    b = loc.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _saisir(page, poignee):
    """Appuie sur la poignée et bouge assez pour que le glisser démarre."""
    poignee.scroll_into_view_if_needed()
    x, y = _centre(poignee)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 12, y + 12, steps=3)
    expect(page.locator(".bz-ghost")).to_be_visible()


def _viser(page, loc):
    x, y = _centre(loc)
    page.mouse.move(x, y, steps=4)


def _ordre():
    return [c["macro_id"] for c in api("GET", "/api/lignes")["chantiers"]]


def _poser_en_tete_et_en_queue(premier, dernier):
    ordre = [m for m in _ordre() if m not in (premier, dernier)]
    api("POST", "/api/macros/reorder", {"ordre": [premier, *ordre, dernier]}, attendu=200)


def test_liste_longue_les_chantiers_se_compactent_et_la_page_defile_seule(bz_page):
    """Chantiers ouverts et nombreux : dès qu'on saisit une tâche, tous se replient en cibles
    compactes ; la souris au bas de la fenêtre fait défiler la page jusqu'au chantier voulu ;
    le dépôt marque la tâche « Déplacement… », puis toast avec Annuler, tâche surlignée."""
    source = creer_chantier(uid("Source"))
    t = creer_tache(uid("Voyageuse"), macro_id=source["id"])
    for _ in range(14):
        c = creer_chantier(uid("Remplissage"))
        creer_tache(uid("Occupante"), macro_id=c["id"])
        creer_tache(uid("Occupante"), macro_id=c["id"])
    cible = creer_chantier(uid("Tout en bas"))
    _poser_en_tete_et_en_queue(source["id"], cible["id"])
    bz_page.set_viewport_size({"width": 1280, "height": 720})
    ouvrir_bureau(bz_page, "chantier")
    tache = tache_loc(bz_page, t["id"])
    tache.locator(".bz-task__row").hover()
    _saisir(bz_page, tache.locator(".bz-grip"))
    expect(bz_page.locator("body")).to_have_class(re.compile(r"bz-compact"))
    expect(section_loc(bz_page, source["id"]).locator(".bz-ch__corps")).to_be_hidden()
    tete = section_loc(bz_page, cible["id"]).locator(".bz-ch__head")
    assert tete.bounding_box()["y"] > 720, "la cible doit être hors de l'écran au départ"
    avant = bz_page.evaluate("window.scrollY")
    bz_page.mouse.move(640, 712, steps=3)  # au ras du bas : la page défile toute seule
    bz_page.wait_for_function(
        "(id) => { const r = document.querySelector(`.bz-ch[data-chantier='${id}'] .bz-ch__head`).getBoundingClientRect();"
        " return r.bottom < innerHeight - 100; }", arg=cible["id"], timeout=15000)
    assert bz_page.evaluate("window.scrollY") > avant
    bz_page.mouse.move(640, 360)  # hors des bords : le défilement s'arrête, on vise
    _viser(bz_page, tete)
    expect(section_loc(bz_page, cible["id"])).to_have_class(re.compile(r"is-drop-target"))
    expect(bz_page.locator(".bz-ghost__vers")).to_have_text(f"Déposer dans « {cible['titre']} »")
    retenue = Retenue(bz_page, f"**/api/micros/{t['id']}", methode="PATCH")
    bz_page.mouse.up()
    retenue.attendre()
    expect(bz_page.locator("body")).not_to_have_class(re.compile(r"bz-compact"))
    expect(tache_loc(bz_page, t["id"])).to_have_class(re.compile(r"is-saving"))
    retenue.relacher()
    toast = bz_page.locator(TOAST_OK).filter(has_text=f"Tâche déplacée dans « {cible['titre']} »")
    expect(toast).to_be_visible(timeout=10000)
    expect(section_loc(bz_page, cible["id"]).locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1, timeout=10000)
    assert ligne(t["id"])["macro_id"] == cible["id"]
    toast.get_by_role("button", name="Annuler").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche remise dans")).to_be_visible(timeout=10000)
    assert ligne(t["id"])["macro_id"] == source["id"]


def test_deposer_dans_un_chantier_replie_qui_s_entrouvre_au_survol(bz_page):
    """Un chantier replié reste une cible ; survolé un moment, il s'entrouvre (on voit ce qu'il
    contient) ; après le dépôt il reste replié, et la tâche y est."""
    a = creer_chantier(uid("Départ"))
    b = creer_chantier(uid("Replié"))
    t = creer_tache(uid("Mobile"), macro_id=a["id"])
    deja = creer_tache(uid("Déjà là"), macro_id=b["id"])
    ouvrir_bureau(bz_page, "chantier")
    replie = section_loc(bz_page, b["id"])
    replie.locator(".bz-ch__titre").click()
    expect(replie.locator(".bz-ch__corps")).to_be_hidden()
    tache_loc(bz_page, t["id"]).locator(".bz-task__row").hover()
    _saisir(bz_page, tache_loc(bz_page, t["id"]).locator(".bz-grip"))
    _viser(bz_page, replie.locator(".bz-ch__head"))
    expect(replie).to_have_class(re.compile(r"is-drop-target"))
    expect(replie).to_have_class(re.compile(r"is-peek"), timeout=3000)
    expect(replie.locator(f".bz-task[data-id='{deja['id']}']")).to_be_visible()
    bz_page.mouse.up()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Tâche déplacée")).to_be_visible(timeout=10000)
    assert ligne(t["id"])["macro_id"] == b["id"]
    expect(replie.locator(".bz-ch__titre")).to_have_attribute("aria-expanded", "false")
    expect(replie.locator(".bz-ch__corps")).to_be_hidden()


def test_mode_statut_un_plateau_de_chantiers_sert_de_cible(bz_page):
    """Mode Statut (pas de blocs de chantier) : saisir une tâche montre un plateau des chantiers ;
    le chantier actuel est marqué ; lâcher sur un autre déplace la tâche."""
    a = creer_chantier(uid("Plateau A"))
    b = creer_chantier(uid("Plateau B"))
    t = creer_tache(uid("Du plateau"), macro_id=a["id"])
    ouvrir_bureau(bz_page)
    tache = section_statut(bz_page, "a_lancer").locator(f".bz-task[data-id='{t['id']}']")
    tache.locator(".bz-task__row").hover()
    _saisir(bz_page, tache.locator(".bz-grip"))
    plateau = bz_page.locator(".bz-plateau")
    expect(plateau).to_be_visible()
    expect(plateau.locator(f".bz-plateau__cible[data-drop='{a['id']}']")).to_contain_text("actuel")
    cible = plateau.locator(f".bz-plateau__cible[data-drop='{b['id']}']")
    cible.scroll_into_view_if_needed()
    _viser(bz_page, cible)
    expect(cible).to_have_class(re.compile(r"is-drop-target"))
    bz_page.mouse.up()
    expect(plateau).to_have_count(0)
    expect(bz_page.locator(TOAST_OK).filter(has_text=f"Tâche déplacée dans « {b['titre']} »")).to_be_visible(timeout=10000)
    expect(tache.locator(".bz-task__chantier")).to_have_text(b["titre"], timeout=10000)


def test_echap_annule_sans_rien_envoyer(bz_page):
    a = creer_chantier(uid("Reste"))
    b = creer_chantier(uid("Jamais"))
    t = creer_tache(uid("Hésitante"), macro_id=a["id"])
    ouvrir_bureau(bz_page, "chantier")
    envois = []
    bz_page.on("request", lambda r: r.method == "PATCH" and "/api/micros/" in r.url and envois.append(r.url))
    tache_loc(bz_page, t["id"]).locator(".bz-task__row").hover()
    _saisir(bz_page, tache_loc(bz_page, t["id"]).locator(".bz-grip"))
    _viser(bz_page, section_loc(bz_page, b["id"]).locator(".bz-ch__head"))
    expect(section_loc(bz_page, b["id"])).to_have_class(re.compile(r"is-drop-target"))
    bz_page.keyboard.press("Escape")
    expect(bz_page.locator(TOAST_INFO).filter(has_text="Déplacement annulé")).to_be_visible(timeout=5000)
    expect(bz_page.locator(".bz-ghost")).to_have_count(0)
    expect(bz_page.locator("body")).not_to_have_class(re.compile(r"bz-compact|bz-dragging"))
    bz_page.mouse.move(300, 300, steps=3)  # bouger encore ne relance pas le geste
    expect(bz_page.locator(".bz-ghost")).to_have_count(0)
    bz_page.mouse.up()
    expect(bz_page.locator("dialog[open]")).to_have_count(0)  # relâcher après Échap n'est pas un clic
    expect(section_loc(bz_page, a["id"]).locator(f".bz-task[data-id='{t['id']}']")).to_be_visible()
    bz_page.wait_for_timeout(500)
    assert envois == [] and ligne(t["id"])["macro_id"] == a["id"]


def test_reordonner_un_chantier_en_le_glissant(bz_page):
    """Un trait d'insertion montre où le chantier va se placer (avant / après la cible)."""
    a = creer_chantier(uid("Glissé"))
    b = creer_chantier(uid("Repère"))
    _poser_en_tete_et_en_queue(a["id"], b["id"])
    ouvrir_bureau(bz_page, "chantier")
    tete_a = section_loc(bz_page, a["id"]).locator(".bz-ch__head")
    tete_a.hover()
    _saisir(bz_page, tete_a.locator(".bz-grip"))
    repere = section_loc(bz_page, b["id"])
    repere.scroll_into_view_if_needed()
    boite = repere.bounding_box()
    bz_page.mouse.move(boite["x"] + boite["width"] / 2, boite["y"] + boite["height"] * 0.8, steps=4)
    expect(repere).to_have_class(re.compile(r"is-insert-after"))
    expect(bz_page.locator(".bz-ghost__vers")).to_have_text(f"Après « {b['titre']} »")
    bz_page.mouse.up()
    expect(bz_page.locator(TOAST_OK).filter(has_text="déplacé")).to_be_visible(timeout=10000)
    # Juste après le repère, pas « dernier » : les autres tests du même bac créent des
    # chantiers en parallèle (xdist), qui se rangent en queue.
    ordre = _ordre()
    assert ordre.index(a["id"]) == ordre.index(b["id"]) + 1


def test_sans_glisser_au_clavier_ou_par_le_menu(bz_page):
    """Entrée sur la poignée d'une tâche : « Déplacer vers… » (flèches pour choisir) ; flèches sur
    la poignée d'un chantier : une place, le focus reste sur la poignée."""
    a = creer_chantier(uid("Clavier A"))
    b = creer_chantier(uid("Clavier B"))
    t = creer_tache(uid("Au clavier"), macro_id=a["id"])
    _poser_en_tete_et_en_queue(a["id"], b["id"])
    ouvrir_bureau(bz_page, "chantier")
    poignee = tache_loc(bz_page, t["id"]).get_by_role("button", name="Déplacer la tâche vers un autre chantier")
    poignee.focus()
    bz_page.keyboard.press("Enter")
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    expect(dlg).to_contain_text("Déplacer vers…")
    expect(dlg.get_by_role("button", name=re.compile(re.escape(a["titre"])))).to_be_disabled()
    choix = dlg.get_by_role("button", name=b["titre"], exact=True)
    choix.focus()
    bz_page.keyboard.press("Enter")
    expect(bz_page.locator(TOAST_OK).filter(has_text=f"Tâche déplacée dans « {b['titre']} »")).to_be_visible(timeout=10000)
    expect(dlg).to_have_count(0)
    assert ligne(t["id"])["macro_id"] == b["id"]

    grip = section_loc(bz_page, a["id"]).get_by_role("button", name=f"Déplacer le chantier {a['titre']}")
    grip.focus()
    avant = _ordre().index(a["id"])
    bz_page.keyboard.press("ArrowDown")
    expect(bz_page.locator(TOAST_OK).filter(has_text="Chantier descendu")).to_be_visible(timeout=10000)
    assert _ordre().index(a["id"]) == avant + 1
    expect(section_loc(bz_page, a["id"]).locator(".bz-grip")).to_be_focused()
