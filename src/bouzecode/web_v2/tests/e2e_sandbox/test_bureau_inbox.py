# [desc] Bureau — ce qui t'attend (SPEC §4.2), par catégorie d'action : vérifier et clore un travail rendu, reprendre un agent arrêté, débloquer un lancement impossible (action manuelle), répondre à une question ou valider un plan hors tâche, intégrer ; une seule apparition par mode, action sur la carte dans les deux modes ; consigne en file. [/desc]
"""Ce qui attend un geste, prouvé sur de vrais agents du faux LLM."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_OK, Retenue, api, attendre, attendre_statut, bz_browser, bz_page, creer_chantier, creer_tache,
    choisir_mode, deplier, ligne, ouvrir_bureau, point_hors_tache, section_loc, section_statut, tache_loc, uid, bande,
    groupe_a_traiter,
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
    "services/work/taches_*.py",
    "services/work/inbox.py",
    "services/work/bureau_lignes.py",
    "services/work/file_messages.py",
    "services/work/dispatch.py",
    "services/work/integration*.py",
    "runtime/runner/**",
)]
AGENT = 90_000

#  Dossier du dépôt disparu : « No such file » sous POSIX, « [WinError 267] Nom de répertoire
#  non valide » (ou WinError 2/3) sous Windows.
DOSSIER_ABSENT = re.compile(r"No such file|WinError (2|3|267)\b")


def _tache_lancee(brief, statut, **lancement):
    c = creer_chantier()
    t = creer_tache(uid("Inbox"), brief, macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT, **lancement}, attendu=200)
    return c, t, attendre_statut(t["id"], statut, delai=120)


def _agent_au_travail(t):
    passage = ((t or {}).get("passages") or [{}])[0]
    return bool(passage.get("agent_id")) and passage.get("etat") in ("thinking", "running")


def test_travail_rendu_a_verifier_voir_puis_valider_et_clore(bz_page):
    """Une réponse finale rendue : la tâche est sous « Vérifier et clore », « À vérifier », avec le
    résumé du passage ; « Voir le travail » déplie le récap ; « Valider et clore » la range,
    « Annuler » la rouvre."""
    _, t, _ = _tache_lancee("Livrer.\n[scn:recap]", "a_relire")
    ouvrir_bureau(bz_page)
    groupe = groupe_a_traiter(bz_page, "verifier")
    expect(groupe.locator(".bz-cat__titre")).to_contain_text("Vérifier et clore", timeout=20000)
    tache = groupe.locator(f".bz-task[data-id='{t['id']}']")
    expect(tache).to_have_class(re.compile(r"is-attention"), timeout=20000)
    expect(tache.locator(".bz-task__badge")).to_contain_text("À vérifier")
    expect(tache.locator(".bz-task__meta")).not_to_be_empty()
    b = bande(bz_page, t["id"])
    b.get_by_role("button", name="Voir le travail").click()
    expect(tache.locator(".bz-task__titre")).to_have_attribute("aria-expanded", "true")
    expect(tache.locator(".bz-passage .bz-recap")).to_be_visible()
    b.get_by_role("button", name="Valider et clore").click()
    toast = bz_page.locator(TOAST_OK).filter(has_text="Tâche validée et close")
    expect(toast).to_be_visible(timeout=10000)
    expect(section_statut(bz_page, "a_moi").locator(f".bz-task[data-id='{t['id']}']")).to_have_count(0, timeout=15000)
    toast.get_by_role("button", name="Annuler").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="rouverte")).to_be_visible(timeout=10000)
    assert ligne(t["id"])["statut_ui"] == "brouillon"


def test_une_tache_qui_t_attend_n_apparait_qu_une_fois_dans_chaque_mode(bz_page):
    """Mode Statut : dans « À traiter » seulement. Mode Chantier : en tête de son chantier,
    surlignée. Jamais deux fois."""
    c, t, _ = _tache_lancee("[scn:reply]", "a_relire")
    creer_tache(uid("Brouillon voisin"), macro_id=c["id"])
    ouvrir_bureau(bz_page)
    expect(tache_loc(bz_page, t["id"])).to_have_count(1, timeout=20000)
    expect(section_statut(bz_page, "a_moi").locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1)
    choisir_mode(bz_page, "chantier")
    expect(tache_loc(bz_page, t["id"])).to_have_count(1)
    premiere = section_loc(bz_page, c["id"]).locator(".bz-ch__corps .bz-task").first
    expect(premiere).to_have_attribute("data-id", t["id"])
    expect(premiere).to_have_class(re.compile(r"is-attention"))


def test_tache_en_echec_continuer(bz_page):
    """Tâche arrêtée à la demande : elle est sous « Reprendre un agent arrêté », dite « Arrêté par
    toi » (pas « planté ») ; sa bande propose « Continuer » (agent joignable), qui fait reprendre
    le même agent — sans déplier la tâche."""
    c = creer_chantier()
    t = creer_tache(uid("Continuera"), "[scn:slow]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    #  « En cours » couvre aussi la préparation (aucun agent encore) : arrêter là teste un autre
    #  chemin (lancement annulé, rien à continuer). On attend que l'agent travaille VRAIMENT.
    attendre(lambda: _agent_au_travail(ligne(t["id"])), 60, message="l'agent [scn:slow] ne travaille pas")
    api("POST", f"/api/micros/{t['id']}/arreter", {}, attendu=200)
    l = attendre_statut(t["id"], "en_echec", 60)
    ouvrir_bureau(bz_page)
    assert l["motif"] == "arrete", (l["motif"], l.get("raison_echec"))
    tache = tache_loc(bz_page, t["id"])
    expect(tache).to_have_attribute("data-motif", "arrete", timeout=20000)
    expect(groupe_a_traiter(bz_page, "reprendre").locator(f".bz-task[data-id='{t['id']}']")).to_have_count(1)
    expect(tache.locator(".bz-task__badge")).to_contain_text("Arrêté par toi")
    bouton = bande(bz_page, t["id"]).get_by_role("button", name="Continuer")
    if not l["joignable"]:
        expect(bouton).to_have_count(0)
        return
    expect(bouton).to_have_attribute("title", "Même agent, même conversation : il reprend là où il s'est arrêté.")
    expect(bouton).to_have_text("Continuer…")
    bouton.click()
    # « Continuer… » ouvre un message optionnel : ici on reprend sans message.
    zone = tache.locator(".bz-consigne")
    expect(zone.get_by_label("Message pour l'agent (optionnel)")).to_be_focused()
    zone.get_by_role("button", name="Continuer").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="reprend")).to_be_visible(timeout=30000)
    attendre_statut(t["id"], {"en_cours", "a_relire"}, 60)


def test_plan_hors_tache_a_valider(bz_page):
    """Point hors tâche « Plan » : une ligne (« Plan à valider ») ; dépliée, le plan en markdown
    puis les options, verrouillées au premier clic."""
    titre = uid("Plan libre")
    api("POST", f"/api/projects/{DEPOT}/tickets", {"title": "e2e", "prompt": f"{titre}\n[scn:plan]", "defer": False},
        attendu=201)
    ouvrir_bureau(bz_page)
    carte = point_hors_tache(bz_page, "plan", titre)
    expect(carte.locator(".bz-task__badge")).to_contain_text("Plan à valider")
    expect(groupe_a_traiter(bz_page, "decider").locator(".bz-point[data-type='plan']").filter(has_text=titre)).to_have_count(1)
    plan = carte.locator(".bz-plan")
    expect(plan).to_be_visible()
    expect(plan.locator(".bz-md li").first).to_contain_text("Écrire un test qui échoue", timeout=15000)
    boutons = carte.locator(".bz-q__opt")
    expect(boutons.first).to_be_visible()
    retenue = Retenue(bz_page, "**/api/agents/*/messages", methode="POST")
    boutons.first.click()
    retenue.attendre()
    expect(boutons.first).to_have_attribute("aria-busy", "true")
    expect(boutons.nth(1)).to_be_disabled()
    retenue.relacher()
    expect(carte.locator(".bz-q__ok")).to_contain_text("Réponse envoyée", timeout=10000)
    expect(bz_page.locator(".bz-point[data-type='plan']").filter(has_text=titre)).to_have_count(0, timeout=AGENT)


def test_integrer_le_travail_d_un_passage(bz_page):
    """Copie isolée + commit (scn:tools) : le passage est « intégrable » ; Intégrer merge et le dit."""
    _, t, l = _tache_lancee("Écrire NOTES.md.\n[scn:tools]", "a_relire", isolation="worktree")
    p = l["passages"][0]
    ouvrir_bureau(bz_page, "a_moi")
    tache = deplier(bz_page, t["id"])
    if not p.get("integrable"):
        expect(tache.locator(".bz-passage").get_by_role("button", name="Intégrer")).to_have_count(0)
        return
    bouton = tache.locator(".bz-passage").get_by_role("button", name="Intégrer")
    bouton.click()
    expect(bz_page.locator(TOAST_OK)).to_be_visible(timeout=120000)
    attendre(lambda: ligne(t["id"])["passages"][0].get("integre") is True, 60, 1, "passage intégré")


def test_mode_chantier_repondre_sur_place(bz_page):
    """Mode Chantier : la tâche dont l'agent pose une question est en tête de son chantier, la
    question et ses options sur la carte ; on répond sans déplier ni quitter le chantier."""
    c = creer_chantier()
    t = creer_tache(uid("Question chantier"), "Choisir.\n[scn:question]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    ouvrir_bureau(bz_page, "chantier")
    tache = section_loc(bz_page, c["id"]).locator(f".bz-task[data-id='{t['id']}']")
    expect(tache).to_have_attribute("data-statut", "a_repondre", timeout=AGENT)
    bloc = bande(bz_page, t["id"]).locator(".bz-q")
    expect(bloc).to_contain_text("Quelle base")
    bloc.get_by_role("button", name="SQLite").click()
    expect(bloc.locator(".bz-q__ok")).to_contain_text("Réponse envoyée", timeout=10000)
    attendre_statut(t["id"], "a_relire")


def test_consigne_a_un_agent_en_cours_est_ajoutee_au_brief_et_transmise(bz_page):
    c = creer_chantier()
    t = creer_tache(uid("Consigne"), "[scn:slow]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(t["id"], "en_cours", 60)
    ouvrir_bureau(bz_page, "en_cours")
    tache = deplier(bz_page, t["id"])
    tache.get_by_role("button", name="Ajouter une consigne…").click()
    zone = tache.locator(".bz-consigne textarea")
    expect(zone).to_be_focused()
    tache.locator(".bz-consigne").get_by_role("button", name="Envoyer").click()
    expect(tache.locator(".bz-consigne .field__error")).to_contain_text("Écris la consigne")
    zone.fill("Pense aussi au cas vide.")
    tache.locator(".bz-consigne").get_by_role("button", name="Envoyer").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Consigne ajoutée au brief")).to_be_visible(timeout=15000)
    expect(tache.locator(".bz-consigne")).to_have_count(0)
    # Tout geste donne un signal : la carte montre la consigne transmise, horodatée.
    expect(tache.locator(".bz-task__transmis")).to_contain_text("✎ Précision transmise à", timeout=20000)
    assert "Pense aussi au cas vide." in api("GET", f"/api/micros/{t['id']}")["micro"]["prompt"]


def test_lancement_impossible_action_manuelle_corriger_et_relancer(bz_page, tmp_path):
    """Le dépôt a disparu du disque : l'agent n'a jamais démarré. La tâche est sous « Action
    manuelle requise », « Lancement impossible » avec la cause ; « Corriger et relancer… » ouvre le
    lancement, où l'on choisit un autre dépôt ; l'agent part."""
    dossier = tmp_path / "disparu"
    dossier.mkdir()
    slug = uid("disparu")
    api("POST", "/api/projects", {"name": slug, "path": str(dossier), "description": "e2e"}, attendu=None)
    slug = next(p["slug"] for p in api("GET", "/api/projects")["projects"] if p["path"] == str(dossier))
    dossier.rmdir()
    t = creer_tache(uid("Sans dépôt"), "[scn:reply]")
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": slug}, attendu=200)
    l = attendre_statut(t["id"], "en_echec", 60)
    assert l["motif"] == "lancement"
    ouvrir_bureau(bz_page)
    groupe = groupe_a_traiter(bz_page, "debloquer")
    expect(groupe.locator(".bz-cat__titre")).to_contain_text("Action manuelle requise", timeout=20000)
    tache = groupe.locator(f".bz-task[data-id='{t['id']}']")
    expect(tache.locator(".bz-task__badge")).to_contain_text("Lancement échoué")
    expect(tache.locator(".bz-task__meta")).to_contain_text(DOSSIER_ABSENT)
    bande(bz_page, t["id"]).get_by_role("button", name="Corriger et relancer…").click()
    dlg = bz_page.locator("dialog.bz-launch[open]")
    expect(dlg).to_be_visible()
    dlg.get_by_label("Dépôt").select_option(DEPOT)
    dlg.locator("[data-role=go]").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="Agent lancé")).to_be_visible(timeout=30000)
    attendre_statut(t["id"], {"en_cours", "a_relire"}, 90)
