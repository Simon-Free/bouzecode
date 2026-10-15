# [desc] E2E des frottements relevés en pilotant le Bureau avec un vrai modèle : infobulle du chantier, un seul « Lancer », toast de lancement durable avec « Ouvrir », reprise visible tout de suite, « Continuer » avec un message, coût agrégé avec les sous-agents. [/desc]
"""Frottements du 2026-09-24 (rapport du pilote), vus dans le navigateur contre le bac à sable."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    BASE, DEPOT, MARQUES, TOAST_OK, api, attendre, attendre_statut, bz_browser, bz_page, creer_chantier,
    creer_tache, deplier, ouvrir_bureau, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "static/js/bureau/**",
    "static/js/conversations/panel/costs.js",
    "static/js/conversations/panel/header_actions.js",
    "routes/sessions/**",
    "services/sessions/costs.py",
    "services/work/taches_actions.py",
    "services/work/liveness.py",
    "services/work/fleet.py",
)]
AGENT = 90_000


def test_l_infobulle_nomme_le_chantier_dans_les_deux_modes(bz_page):
    c = creer_chantier(uid("Chantier infobulle"))
    t = creer_tache(uid("Infobulle"), macro_id=c["id"])
    for mode in ("chantier", "statut"):
        ouvrir_bureau(bz_page, mode)
        ligne = tache_loc(bz_page, t["id"]).locator(".bz-task__row")
        expect(ligne).to_have_attribute("title", re.compile(re.escape(c["titre"])))
        expect(ligne).not_to_have_attribute("title", re.compile("Sans chantier"))


def test_lancer_un_seul_bouton_et_toast_durable_avec_ouvrir(bz_page):
    c = creer_chantier()
    t = creer_tache(uid("Toast"), "Travail.\n[scn:reply]", macro_id=c["id"])
    ouvrir_bureau(bz_page, "chantier")
    tache = deplier(bz_page, t["id"])
    visibles = tache.locator("button:visible", has_text=re.compile(r"^Lancer$"))
    expect(visibles).to_have_count(1)
    visibles.first.click()
    dlg = bz_page.locator("dialog.bz-launch[open]")
    dlg.get_by_label("Dépôt").select_option(DEPOT)
    dlg.locator("[data-role=go]").click()
    toast = bz_page.locator(TOAST_OK).filter(has_text="Agent lancé")
    expect(toast).to_be_visible(timeout=30000)
    expect(toast.get_by_role("button", name="Ouvrir")).to_be_visible()
    bz_page.wait_for_timeout(6500)
    expect(toast).to_be_visible()   # ≥ 6 s : le temps de le lire et de cliquer « Ouvrir »
    toast.get_by_role("button", name="Ouvrir").click()
    expect(bz_page).to_have_url(re.compile(r"/conversations\?agent="), timeout=10000)


def test_relancer_meme_agent_passe_en_cours_tout_de_suite(bz_page):
    c = creer_chantier()
    t = creer_tache(uid("Reprise"), "Travail.\n[scn:reply]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    l = attendre_statut(t["id"], "a_relire", 90)
    if not l.get("joignable"):
        pytest.skip("l'agent du passage n'est plus joignable (process recyclé) : rien à reprendre")
    ouvrir_bureau(bz_page, "chantier")
    tache = deplier(bz_page, t["id"])
    tache.get_by_role("button", name="Renvoyer avec un retour…").click()
    dlg = bz_page.locator("dialog.bz-launch[open]")
    dlg.locator("[data-role=retour]").fill("ajoute un test du cas vide")
    dlg.locator("input[value=continuer]").check()
    dlg.locator("[data-role=go]").click()
    expect(bz_page.locator(TOAST_OK).filter(has_text=re.compile("reprend|en file"))).to_be_visible(timeout=30000)
    # Sans attendre le poll : la tâche est « En cours » (Reprise…) et propose la consigne.
    expect(tache).to_have_attribute("data-statut", "en_cours", timeout=2000)
    expect(tache.get_by_role("button", name="Ajouter une consigne…")).to_be_visible(timeout=5000)


def _noeud(cle):
    return next((n for n in api("GET", "/api/agents/tree")["nodes"] if n.get("key") == cle), None)


def _agent_libre(titre, scenario):
    """L'agent lancé, désigné par la clé `agent/<id>` que rend la création de ticket (`defer: false`). Le chercher par son
    titre dans l'arbre pouvait tomber sur le nœud de LANCEMENT (`launching/<ticket>`), dont
    `agent_id` est l'id du ticket : on attendait ensuite un agent qui n'existerait jamais."""
    r = api("POST", f"/api/projects/{DEPOT}/tickets", {"title": "e2e", "prompt": f"{titre}\n[scn:{scenario}]",
                                      "defer": False}, attendu=201)
    assert str(r.get("key") or "").startswith("agent/"), r
    return attendre(lambda: _noeud(r["key"]), 90, message=f"{r['key']} absent de l'arbre")


def _attendre_etat_du_noeud(cle, etat, delai, message):
    vu: list = [None]

    def atteint():
        vu[0] = _noeud(cle)
        return vu[0] if vu[0] and vu[0].get("etat") == etat else None
    try:
        return attendre(atteint, delai, message=message)
    except AssertionError as exc:
        n = vu[0] or {}
        raise AssertionError(f"{exc} ; dernier nœud : etat={n.get('etat')!r} state={n.get('state')!r} "
                             f"liveness={n.get('liveness')!r} returncode={n.get('returncode')!r}") from None


def test_continuer_avec_un_message_le_transmet(bz_page):
    """Page Agents, agent arrêté sans finir : le texte tapé dans le champ du bas part AVEC la
    reprise (« Continuer »), et le champ se vide ; sans texte, la reprise part seule."""
    titre = uid("Plantera")
    noeud = _agent_libre(titre, "crash")
    agent_id = noeud["agent_id"]
    _attendre_etat_du_noeud(noeud["key"], "crashed", 90, "l'agent [scn:crash] n'est pas passé « Arrêté sans finir »")
    bz_page.goto(f"{BASE}/conversations?agent={agent_id}")
    champ = bz_page.locator(".ag-composer__input:visible")
    expect(champ).to_be_visible(timeout=20000)
    champ.fill("reprends par le cas vide")
    bouton = bz_page.locator(".ag-head__actions button:visible", has_text="Continuer")
    expect(bouton).to_have_attribute("title", re.compile("message tapé dans le champ du bas"))
    bouton.click()
    expect(bz_page.locator(TOAST_OK).filter(has_text="reprend avec ton message")).to_be_visible(timeout=30000)
    expect(champ).to_have_value("")
    attendre(lambda: "reprends par le cas vide" in str(
        api("GET", f"/api/sessions/agent/{agent_id}/blocks?plain=1")), 60,
        message="le message joint à « Continuer » n'est pas arrivé dans la conversation")


def test_le_cout_d_une_mission_compte_ses_sous_agents(bz_page):
    agent_id = _agent_libre(uid("Manager coût"), "subagents")["agent_id"]
    attendre(lambda: len(api("GET", f"/api/sessions/agent/{agent_id}/costs?avec_sous_agents=1")
                         .get("sous_agents") or []) >= 1, AGENT / 1000, message="aucun sous-agent lancé")
    bz_page.goto(f"{BASE}/conversations?agent={agent_id}")
    bz_page.locator(".ag-views [data-view=costs]:visible").first.click()
    total = bz_page.locator(".ag-costs__total-tree:visible")
    expect(total).to_contain_text("Total avec sous-agents", timeout=30000)
    expect(total).to_contain_text("unités du tarif")
