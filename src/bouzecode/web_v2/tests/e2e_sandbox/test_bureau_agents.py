# [desc] Bureau — parcours avec de VRAIS agents sur le faux LLM : lancer → relire → faite (U4), dépôt manquant (U5), question depuis le Bureau (U6), relancer avec un retour (U7), agent planté (U8), arrêter (U9). [/desc]
"""Parcours U4 à U9 de SPEC.md. Le scénario du faux LLM se choisit par un tag `[scn:…]` dans le
brief de la tâche (voir tests/sandbox/README.md). Aucune page n'est rechargée : chaque changement
d'état doit arriver à l'écran par le rafraîchissement automatique (R8)."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_ERR, TOAST_OK, Retenue, api, attendre_statut, bz_browser, bz_page, creer_chantier,
    creer_tache, deplier, ligne, ouvrir_bureau, point_hors_tache, simuler_erreur, tache_loc, uid, bande,
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
    "routes/work/fleet.py",
    "routes/sessions/**",
    "services/work/micros.py",
    "services/work/taches_*.py",
    "services/work/inbox.py",
    "services/work/bureau_lignes.py",
    "services/work/dispatch.py",
    "services/work/lexique.py",
    "runtime/runner/**",
    "runtime/pending.py",
)]
AGENT = 90_000  # ms : préparation + premier tour d'un vrai agent


def _dialogue(page):
    return page.locator("dialog.bz-launch[open]")


def _lancer(page, t, depot=DEPOT):
    tache = tache_loc(page, t["id"])
    tache.locator(".bz-task__titre").click()
    # Un seul « Lancer » visible : dépliée, l'action de la ligne s'efface au profit du détail.
    expect(tache.get_by_role("button", name="Lancer", exact=True)).to_have_count(1)
    expect(tache.locator(".bz-task__row .bz-task__action")).to_be_hidden()
    tache.locator(".bz-task__actions").get_by_role("button", name="Lancer", exact=True).click()
    dlg = _dialogue(page)
    expect(dlg).to_be_visible()
    if depot:
        dlg.get_by_label("Dépôt").select_option(depot)
    return dlg


def test_lancer_une_tache_jusqu_a_faite(bz_page):
    """U4 : dialogue (aperçu du prompt) → bouton occupé → toast « Agent lancé » → la tâche passe
    En cours puis À vérifier SANS recharger → Valider et clore → Archivées."""
    c = creer_chantier()
    t = creer_tache(uid("Lancée"), "Faire le travail.\n[scn:reply]", macro_id=c["id"])
    ouvrir_bureau(bz_page, "a_lancer")
    dlg = _lancer(bz_page, t)
    dlg.locator(".bz-launch__apercu summary").click()
    expect(dlg.locator(".bz-launch__prompt")).to_contain_text("Faire le travail.", timeout=10000)
    expect(dlg.get_by_label("Dépôt")).to_have_value(DEPOT)
    go = dlg.locator("[data-role=go]")
    retenue = Retenue(bz_page, f"**/api/micros/{t['id']}/lancer", methode="POST")
    go.click()
    retenue.attendre()
    expect(go).to_have_attribute("aria-busy", "true")
    expect(dlg.get_by_role("button", name="Annuler")).to_be_disabled()
    retenue.relacher()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Agent lancé")).to_be_visible(timeout=30000)
    expect(_dialogue(bz_page)).to_have_count(0)
    # Sans recharger, la tâche passe de « À lancer » à « En cours » puis « À traiter » (mode Statut).
    tache = tache_loc(bz_page, t["id"])
    expect(tache).to_have_attribute("data-statut", "a_relire", timeout=AGENT)
    deplier(bz_page, t["id"])
    expect(tache.locator(".bz-passage")).to_have_count(1)
    expect(tache.locator(".bz-passage")).to_contain_text("Terminé")
    expect(tache.locator(".bz-passage").get_by_role("link", name="Ouvrir la conversation")).to_be_visible()
    bande(bz_page, t["id"]).get_by_role("button", name="Valider et clore").click()
    toast = bz_page.locator(TOAST_OK).filter(has_text="Tâche validée et close")
    expect(toast).to_be_visible(timeout=10000)
    # L'agent du passage est archivé avec la tâche, et le toast le dit (« Annuler » = rouvrir).
    expect(toast).to_contain_text("1 agent archivé")
    expect(toast.get_by_role("button", name="Annuler")).to_be_visible()
    expect(tache_loc(bz_page, t["id"])).to_have_count(0, timeout=10000)
    assert ligne(t["id"])["statut_ui"] == "faite"


def test_lancer_sans_depot_exige_un_choix(bz_page):
    """U5 : sans dépôt (tâche hors chantier, sans dépôt), le dialogue exige le choix AVANT tout
    appel ; un dépôt refusé par le serveur est dit dans le dialogue et la tâche reste Brouillon."""
    t = creer_tache(uid("Sans dépôt"), "[scn:reply]")
    ouvrir_bureau(bz_page, "a_lancer")
    dlg = _lancer(bz_page, t, depot=None)
    expect(dlg.get_by_label("Dépôt")).to_have_value("")
    appels = []
    bz_page.on("request", lambda r: "/lancer" in r.url and appels.append(r.url))
    dlg.locator("[data-role=go]").click()
    expect(dlg.locator(".field[data-invalid=true]")).to_contain_text("Choisis le dépôt")
    expect(dlg.get_by_label("Dépôt")).to_be_focused()
    assert appels == []
    simuler_erreur(bz_page, f"**/api/micros/{t['id']}/lancer", 400, methode="POST",
                   corps={"error": "dépôt « demo-api » inconnu", "code": "depot_inconnu", "suggestions": []})
    dlg.get_by_label("Dépôt").select_option(DEPOT)
    dlg.locator("[data-role=go]").click()
    expect(dlg.locator(".bz-launch__erreur")).to_contain_text("Lancement impossible", timeout=10000)
    expect(dlg.locator(".field[data-invalid=true]")).to_contain_text("inconnu")
    dlg.get_by_role("button", name="Annuler").click()
    assert ligne(t["id"])["statut_ui"] == "brouillon"


def test_une_question_d_agent_se_repond_depuis_le_bureau(bz_page):
    """U6 : la question arrive sur le Bureau sans recharger ; une option clique = réponse ; tout le
    bloc se verrouille ; l'agent reprend et la tâche finit À relire."""
    c = creer_chantier()
    t = creer_tache(uid("Questionneuse"), "Choisir une base.\n[scn:question]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    ouvrir_bureau(bz_page, "a_moi")
    tache = tache_loc(bz_page, t["id"])
    expect(tache).to_have_attribute("data-statut", "a_repondre", timeout=AGENT)
    # Repliée : surlignée, groupée sous « Décider », la question et ses options SUR la carte.
    expect(tache).to_have_class(re.compile(r"is-attention"))
    expect(tache).to_have_attribute("data-motif", "question")
    expect(tache.locator(".bz-task__titre")).to_have_attribute("aria-expanded", "false")
    expect(bz_page.locator(".bz-cat[data-cat='decider']").locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1)
    bloc = bande(bz_page, t["id"]).locator(".bz-q")
    expect(bloc).to_contain_text("Quelle base")
    option = bloc.get_by_role("button", name="SQLite")
    option.click()
    expect(bloc.locator(".bz-q__ok")).to_contain_text("Réponse envoyée", timeout=10000)
    expect(tache).to_have_attribute("data-statut", "a_relire", timeout=AGENT)


def test_question_hors_tache_repondue_dans_la_boite_a_traiter(bz_page):
    """U6 bis : une conversation libre qui pose une question apparaît dans « À traiter » ; réponse
    en texte libre (Entrée) ; erreur simulée → message, texte gardé, bloc déverrouillé."""
    titre = uid("Question libre")
    r = api("POST", f"/api/projects/{DEPOT}/tickets", {"title": "e2e", "prompt": f"{titre}\n[scn:question]",
                                      "defer": False}, attendu=201)
    agent = (r.get("key") or "").replace("agent/", "") or r.get("agent_id", "")
    ouvrir_bureau(bz_page)
    carte = point_hors_tache(bz_page, "question", titre)
    libre = carte.locator(".bz-q__libre")
    libre.fill("PostgreSQL, la base de prod")
    simuler_erreur(bz_page, "**/api/agents/*/messages", 500, methode="POST")
    libre.press("Enter")
    expect(carte.locator(".bz-q__erreur")).to_contain_text("Réponse non transmise", timeout=10000)
    expect(libre).to_have_value("PostgreSQL, la base de prod")
    expect(libre).to_be_editable()
    carte.get_by_role("button", name="Répondre").click()
    expect(carte.locator(".bz-q__ok")).to_contain_text("PostgreSQL, la base de prod", timeout=10000)
    expect(bz_page.locator(".bz-point[data-type=question]").filter(has_text=titre)).to_have_count(0, timeout=AGENT)
    assert agent


def test_relancer_avec_un_retour_nouvel_agent(bz_page):
    """U7 : le prompt du passage 2 contient le récap du passage 1 ET le retour donné."""
    c = creer_chantier()
    t = creer_tache(uid("Itérative"), "Premier jet.\n[scn:recap]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(t["id"], "a_relire")
    ouvrir_bureau(bz_page, "a_moi")
    tache = tache_loc(bz_page, t["id"])
    deplier(bz_page, t["id"])
    tache.get_by_role("button", name="Renvoyer avec un retour…").click()
    dlg = _dialogue(bz_page)
    expect(dlg).to_be_visible()
    dlg.locator("[data-role=retour]").fill("Il manque les tests du cas vide.")
    dlg.get_by_label("Un nouvel agent").check()
    dlg.locator(".bz-launch__apercu summary").click()
    apercu = dlg.locator(".bz-launch__prompt")
    expect(apercu).to_contain_text("Il manque les tests du cas vide.", timeout=10000)
    expect(apercu).to_contain_text("Premier jet.")
    dlg.get_by_label("Dépôt").select_option(DEPOT)
    dlg.locator("[data-role=go]").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Agent lancé")).to_be_visible(timeout=30000)
    prompt = api("GET", f"/api/micros/{t['id']}/prompt")["prompt"]
    assert "Il manque les tests du cas vide." in prompt
    l = attendre_statut(t["id"], "a_relire")
    assert len(l["passages"]) == 2
    assert l["passages"][0]["retour"] == "Il manque les tests du cas vide."
    expect(tache_loc(bz_page, t["id"]).locator(".bz-passage")).to_have_count(2, timeout=30000)
    expect(tache_loc(bz_page, t["id"]).locator(".bz-passage__retour")).to_contain_text("Il manque les tests")


def test_agent_plante_puis_relance(bz_page):
    """U8 : un agent planté (erreur API non retentable) → tâche En échec avec sa raison, dans
    « À traiter » ; « Relancer » repart sur un nouvel agent."""
    c = creer_chantier()
    t = creer_tache(uid("Plantera"), "[scn:crash]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(t["id"], "en_echec", delai=120)
    ouvrir_bureau(bz_page, "a_moi")
    tache = tache_loc(bz_page, t["id"])
    expect(tache).to_have_attribute("data-statut", "en_echec", timeout=20000)
    deplier(bz_page, t["id"])
    expect(tache.locator(".bz-task__meta, .bz-passage").first).to_be_visible()
    expect(tache).to_have_attribute("data-motif", "plante")
    expect(tache.locator(".bz-task__badge")).to_contain_text("Arrêté sans finir")
    relancer = bande(bz_page, t["id"]).get_by_role("button", name="Relancer", exact=True)
    expect(relancer).to_have_attribute("title", "Nouvel agent, environnement préparé à neuf (≈ 30 à 60 s), avec le récap des passages précédents.")
    # Le brief est corrigé (plus de crash) AVANT de relancer : le dialogue l'enregistre d'abord (R9).
    tache.locator(".bz-ed__brief").fill("[scn:reply]")
    relancer.click()
    dlg = _dialogue(bz_page)
    dlg.get_by_label("Dépôt").select_option(DEPOT)
    dlg.locator("[data-role=go]").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Agent lancé")).to_be_visible(timeout=30000)
    assert ligne(t["id"])["corps"] == "[scn:reply]"
    l = attendre_statut(t["id"], "a_relire")
    assert len(l["passages"]) == 2


def test_arreter_un_agent_en_cours(bz_page):
    """U9 : Arrêter → confirmation → « Agent arrêté » → la tâche passe En échec (Continuer / Relancer)."""
    c = creer_chantier()
    t = creer_tache(uid("Longue"), "[scn:slow]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(t["id"], "en_cours", delai=60)
    ouvrir_bureau(bz_page, "en_cours")
    tache = tache_loc(bz_page, t["id"])
    expect(tache).to_have_attribute("data-statut", "en_cours", timeout=20000)
    deplier(bz_page, t["id"])
    tache.get_by_role("button", name="Arrêter").click()
    dlg = bz_page.locator("dialog.ui-dialog[open]")
    expect(dlg).to_contain_text("Arrêter l'agent ?")
    dlg.get_by_role("button", name="Annuler").click()
    expect(tache).to_have_attribute("data-statut", "en_cours")
    tache.get_by_role("button", name="Arrêter").click()
    bz_page.locator("dialog.ui-dialog[open]").get_by_role("button", name="Arrêter").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Agent arrêté")).to_be_visible(timeout=30000)
    l = attendre_statut(t["id"], {"en_echec", "a_relire"}, delai=60)
    assert l["statut_ui"] == "en_echec", l.get("raison_echec")
    assert not l["agent_actif"]
