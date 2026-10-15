# [desc] E2E page Agents — titres lisibles (TODO §6) : un agent lancé avec un prompt de contexte (« Tu travailles dans le dépôt… ») ou un gabarit s'affiche par son OBJECTIF ; le brief complet reste en infobulle. [/desc]
from __future__ import annotations

import os

import pytest

from agents_e2e_support import (  # noqa: F401 — fixtures importées
    DEPOT, MARQUES, api, browser, cle_agent, expect, ouvrir, pg, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre("services/work/titres.py", "services/work/fleet.py",
                                           "services/work/dispatch.py", "static/js/conversations/**")]


def _lancer(prompt: str) -> str:
    """Comme la barre de lancement (`model.js::ticketBody`) : le titre envoyé est la 1re ligne
    du prompt — souvent du CONTEXTE ; c'est le serveur qui doit afficher l'objectif."""
    premiere = next(ligne.strip() for ligne in prompt.splitlines() if ligne.strip())[:200]
    r = api("POST", f"/api/projects/{DEPOT}/tickets", {
        "title": premiere, "prompt": prompt, "typology": "default", "isolation": "worktree",
        "launch": True, "defer": True}, attendu=201)
    return r["ticket_id"]


def _noeud(cle: str) -> dict:
    return next(n for n in api("GET", "/api/agents/tree")["nodes"] if n.get("key") == cle)


def test_un_agent_s_appelle_par_son_objectif_pas_par_son_contexte(pg):
    objectif = f"Écrire le rapport de mesure {uid('r')}"
    prompt = (f"Tu travailles dans le dépôt git `{DEPOT}` (worktree dédié). Commence par lire SPEC.md.\n"
              f"[scn:reply]\n## OBJECTIF (vérifiable)\n{objectif}.\n## PÉRIMÈTRE\n- rapport.md\n")
    cle = cle_agent(_lancer(prompt))
    ouvrir(pg)
    carte = pg.page.locator(f".ag-card[data-key='{cle}']")
    expect(carte.locator(".ag-card__title")).to_have_text(objectif, timeout=30000)
    noeud = _noeud(cle)
    assert noeud["title"] == objectif and noeud["title_full"].startswith("Tu travailles dans le dépôt")
    dossier = os.environ.get("BZ_E2E_CAPTURES")
    if dossier:
        pg.page.screenshot(path=os.path.join(dossier, "apres_agents_titres.png"), full_page=True)


def test_une_demande_enveloppee_par_un_gabarit_prend_le_titre_de_la_demande(pg):
    demande = f"Brancher le scraping du Castor {uid('c')}"
    ticket = _lancer("Dans le chantier « Démo », crée et lance une tâche dont le brief est exactement le "
                     f"texte suivant :\n\n{demande}. Garde le format JSON actuel.\n[scn:reply]")
    assert _noeud(cle_agent(ticket))["title"] == demande
