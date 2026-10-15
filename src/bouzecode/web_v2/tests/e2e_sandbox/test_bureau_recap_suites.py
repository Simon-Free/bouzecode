# [desc] Bureau — le récap d'un passage mène aux tâches créées pour ses points « reste à faire » / « à décider », et un brouillon « Fusionner la branche agent/XXXX » s'archive seul (avec sa trace) quand l'agent intègre cette branche. [/desc]
"""Sur de vrais agents du faux LLM : clôture avec des points laissés (scn:recap), et agent qui
intègre lui-même sa branche pendant qu'un brouillon de fusion l'attend (scn:integre-soi-meme)."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, api, attendre, attendre_statut, bz_browser, bz_page, creer_chantier, creer_tache, deplier, ligne,
    ouvrir_bureau, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/bureau.html",
    "static/css/bureau.css",
    "static/js/bureau/**",
    "static/js/lib/**",
    "routes/work/micros/**",
    "services/work/taches_*.py",
    "services/work/suites_cloture.py",
    "services/work/cloture_micros.py",
    "services/work/brouillons_integres.py",
    "services/work/bureau_lignes.py",
    "services/work/integration*.py",
)]
AGENT = 90_000
RESTE = "Ajouter un test de non-régression sur l'export CSV"
DECISION = "Garder le séparateur `;` ou passer à `,` ?"


def test_le_recap_d_un_passage_mene_aux_taches_creees_pour_ses_points(bz_page):
    """L'agent clôt avec un « reste à faire » et un « à décider » : chaque point du passage dit
    « → tâche créée : … · statut », et le lien déplie la tâche dans le Bureau."""
    c = creer_chantier()
    t = creer_tache(uid("Récap"), "Livrer.\n[scn:recap]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    suites = attendre_statut(t["id"], "a_relire", delai=120)["passages"][0]["recap"]["suites"]
    [reste], [decision] = suites["reste"], suites["a_decider"]
    assert (reste["titre"], reste["statut_ui"]) == (RESTE, "brouillon")
    assert (decision["titre"], decision["statut_ui"]) == (DECISION, "a_decider")

    ouvrir_bureau(bz_page)
    points = deplier(bz_page, t["id"]).locator(".bz-passage .bz-recap li")
    point_reste = points.filter(has_text="Ajouter un test de non-régression")
    expect(point_reste.locator(".bz-suite")).to_have_text(f"→ tâche créée : {RESTE} · à lancer")
    expect(points.filter(has_text="Garder le séparateur").locator(".bz-suite")).to_have_text(
        f"→ tâche créée : {DECISION} · à décider")
    point_reste.locator(".bz-suite__lien").click()
    cible = tache_loc(bz_page, reste["id"])
    expect(cible.locator(".bz-task__titre")).to_have_attribute("aria-expanded", "true")
    expect(cible).to_be_in_viewport()


def test_un_brouillon_de_fusion_s_archive_quand_l_agent_integre_sa_branche(bz_page):
    """Un brouillon « Fusionner la branche agent/<ticket> » attend pendant que l'agent travaille ;
    l'agent intègre lui-même : le brouillon passe dans les archivées et sa ligne dit pourquoi."""
    c = creer_chantier()
    t = creer_tache(uid("Intègre"), "Livrer LIVRE.md.\n[scn:integre-soi-meme]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT, "isolation": "worktree"}, attendu=200)
    passage = attendre_statut(t["id"], "a_repondre", delai=120)["passages"][0]
    branche = passage["branche"] or f"agent/{passage['ticket_id']}"
    brouillon = creer_tache(f"Fusionner la branche {branche} dans main", macro_id=c["id"])
    ouvrir_bureau(bz_page, "chantier")
    ligne_brouillon = tache_loc(bz_page, brouillon["id"])
    expect(ligne_brouillon).to_have_attribute("data-statut", "brouillon", timeout=20000)

    api("POST", f"/api/agents/{passage['agent_id']}/messages", {"text": "Oui", "mode": "refuse"}, attendu=200)

    attendre(lambda: (ligne(brouillon["id"]) or {}).get("statut_ui") == "faite", AGENT / 1000, 1,
             "brouillon de fusion archivé")
    #  Le brouillon s'archive dès que git voit la branche fusionnée ; le ticket, lui, n'est clos
    #  « intégré » qu'au constat de fin de run (tick du watchdog) : quelques secondes plus tard.
    attendre(lambda: ligne(t["id"])["passages"][0]["integre"] is True, 60, 1, "passage dit intégré")
    ouvrir_bureau(bz_page, "archivees")
    archivee = tache_loc(bz_page, brouillon["id"])
    expect(archivee).to_have_attribute("data-statut", "faite", timeout=20000)
    expect(archivee.locator(".bz-task__meta")).to_contain_text(
        f"Archivée automatiquement : branche {branche} intégrée le ")
