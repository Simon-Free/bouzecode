# [desc] Scénarios COMPOSÉS rejouant la recette avec un vrai modèle : manager en worktree qui délègue puis intègre, enfant qui plante, relance « même agent » après la réponse finale — suivis dans le Bureau et la page Agents, sous le vérificateur d'invariants. [/desc]
"""Les enchaînements réels (et non des gestes isolés) : c'est là que la recette du 2026-09-24
avec DeepSeek a trouvé ses bugs — manager affiché « Attend ses sous-agents » alors qu'il
travaille, agent tué par sa propre intégration, sous-agent qui ne voit pas le travail de son
parent. Le vérificateur d'invariants (conftest.py) tourne pendant chaque test."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    BASE, DEPOT, MARQUES, TOAST_OK, api, attendre, attendre_statut, bz_browser, bz_page, creer_chantier,
    creer_tache, deplier, ligne, ouvrir_bureau, tache_loc, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre(
    "static/js/bureau/**", "static/js/conversations/**", "static/js/lib/**", "templates/bureau.html",
    "templates/conversations.html", "routes/work/**", "routes/sessions/**", "services/work/**",
    "services/sessions/**", "runtime/runner/**", "runtime/warmpool.py",
    "../backend/tools/environment.py", "../backend/multi_agent/tools.py",
    "../backend/multi_agent/outil_agent.py", "../backend/multi_agent/appel_agent.py",
    "../backend/multi_agent/lancement_web.py", "../backend/multi_agent/attente_web.py",
    "../backend/multi_agent/travail_non_commite.py", "../backend/multi_agent/outils_enfants.py",
    "../backend/multi_agent/outils_flotte.py", "../backend/multi_agent/schema_agent.py",
    "../backend/multi_agent/schemas.py",
)]
AGENT = 120_000  # ms


def _arbre() -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/api/agents/tree?offset=0&limit=500", timeout=30) as r:
        return json.loads(r.read().decode())["nodes"]


def _enfants(agent_id: str) -> list[dict]:
    return [n for n in _arbre() if str(n.get("parent") or "").replace("agent/", "") == agent_id]


def _depot() -> str:
    projets = api("GET", "/api/projects")["projects"]
    return next(p["path"] for p in projets if p["slug"] == DEPOT)


def _fichiers_de_main() -> set[str]:
    sortie = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main"], cwd=_depot(),
                            capture_output=True, text=True, check=True).stdout
    return set(sortie.split())


def _branches() -> str:
    """Pour le message d'échec : où sont passés les commits des lots (log de chaque branche)."""
    return subprocess.run(["git", "log", "--all", "--oneline", "--decorate", "-15"], cwd=_depot(),
                          capture_output=True, text=True).stdout


def _lancer_manager(scenario: str) -> tuple[dict, str]:
    c = creer_chantier()
    t = creer_tache(uid("Manager"), f"Coordonner deux lots.\n[scn:{scenario}]", macro_id=c["id"])
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    agent_id = attendre(lambda: (ligne(t["id"])["passages"] or [{}])[0].get("agent_id"), 60, 0.5,
                        "agent du manager")
    return t, agent_id


def test_un_manager_en_worktree_delegue_ses_lots_puis_integre_tout(bz_page):
    """Worktree, spec non commitée, 2 sous-agents (worktree + commit + intégration), réveil,
    intégration du manager : tout arrive dans la base, le Bureau suit sans recharger."""
    t, manager = _lancer_manager("manager-worktree")
    ouvrir_bureau(bz_page)
    tache = tache_loc(bz_page, t["id"])
    expect(tache).to_have_attribute("data-statut", "a_relire", timeout=AGENT)
    #  L'arbre est servi par un cache (servir, puis recalculer) : on attend qu'il rattrape.
    attendre(lambda: sorted(e["etat"] for e in _enfants(manager)) == ["finished", "finished"], 30, 1,
             "deux sous-agents terminés dans l'arbre")
    try:
        attendre(lambda: {"enfant_a.md", "enfant_b.md"} <= _fichiers_de_main(), 30, 1,
                 "lots des sous-agents dans main")
    except AssertionError as exc:
        raise AssertionError(f"{exc} ; main contient {sorted(_fichiers_de_main())} ; "
                             f"branches : {_branches()}") from None
    # Page Agents : le manager et ses deux sous-agents, sans « arrêté ».
    bz_page.goto(f"{BASE}/conversations?agent={manager}")
    carte = bz_page.locator(f"[data-key='agent/{manager}']").first
    expect(carte).to_be_visible(timeout=30000)
    expect(bz_page.locator("#conv-panels")).to_contain_text("Terminé", timeout=30000)
    expect(carte).to_contain_text("2 sous-agents", timeout=30000)
    expect(carte).not_to_contain_text("arrêté")


def test_un_sous_agent_qui_plante_n_est_jamais_compte_comme_vivant(bz_page):
    """Un enfant réussit, l'autre plante : le manager n'attend que tant qu'un enfant travaille,
    est réveillé quand les deux sont terminaux, et conclut ; l'enfant planté est dit tel."""
    t, manager = _lancer_manager("manager-worktree-crash")
    attendre_statut(t["id"], "a_relire", delai=AGENT / 1000)
    attendre(lambda: sorted(e["etat"] for e in _enfants(manager)) == ["crashed", "finished"], 30, 1,
             "un sous-agent planté, l'autre terminé")
    bz_page.goto(f"{BASE}/conversations?agent={manager}")
    carte = bz_page.locator(f"[data-key='agent/{manager}']").first
    expect(carte).to_contain_text("1 arrêté", timeout=30000)
    expect(carte).not_to_contain_text("Attend ses sous-agents")


def test_relancer_le_meme_agent_apres_sa_reponse_finale_le_montre_au_travail(bz_page):
    """Retour donné à un agent déjà conclu (même agent) : la tâche repasse « En cours » et son
    agent n'est JAMAIS affiché « Attend ses sous-agents » ; le complément arrive dans la base."""
    t, manager = _lancer_manager("manager-worktree")
    attendre_statut(t["id"], "a_relire", delai=AGENT / 1000)
    #  « Déjà conclu » = après sa VRAIE conclusion : la tâche passe « à relire » dès la 1re
    #  réponse finale (délégation faite, enfants vite finis), AVANT que le réveil automatique
    #  (tick de 8 s) ne lui rende les verdicts. Relancé dans cet intervalle, il reçoit le retour
    #  ET le réveil dans le même tour (la file ne perd plus rien) : le faux LLM suit alors le
    #  seul tag du retour et saute l'intégration du réveil. On attend donc qu'elle soit faite.
    attendre(lambda: "SPEC_COMMUNE.md" in _fichiers_de_main(), AGENT / 1000, 1,
             "intégration du manager après son réveil")
    attendre_statut(t["id"], "a_relire", delai=AGENT / 1000)
    ouvrir_bureau(bz_page, "a_moi")
    tache = tache_loc(bz_page, t["id"])
    deplier(bz_page, t["id"])
    tache.get_by_role("button", name="Renvoyer avec un retour…").click()
    dlg = bz_page.locator("dialog.bz-launch[open]")
    expect(dlg).to_be_visible()
    dlg.locator("[data-role=retour]").fill("Il manque RETOUR.md. [scn:relance-apres-final]")
    dlg.get_by_label("Le même agent").check()
    dlg.locator("[data-role=go]").click()
    expect(bz_page.locator(TOAST_OK).first).to_be_visible(timeout=30000)
    expect(tache).to_have_attribute("data-statut", "en_cours", timeout=30000)
    fin = time.time() + 30
    while time.time() < fin and ligne(t["id"])["statut_ui"] == "en_cours":
        etat = next(n["etat"] for n in _arbre() if n.get("agent_id") == manager)
        assert etat != "orchestrating", "le manager relancé travaille : il n'attend personne"
        time.sleep(0.5)
    expect(tache).to_have_attribute("data-statut", "a_relire", timeout=AGENT)
    attendre(lambda: "RETOUR.md" in _fichiers_de_main(), 90, 1, "complément du retour dans main")

