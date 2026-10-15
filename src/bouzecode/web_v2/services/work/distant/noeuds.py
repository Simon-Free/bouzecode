# [desc] Noeuds de l'arbre de flotte pour les tickets executes sur Rundeck (aucun agent local ne les porterait). [/desc]
"""Sans ces noeuds, une tache lancee sur Rundeck n'apparaitrait nulle part dans l'arbre : le
noeud d'un ticket y vient de la fiche de son agent, et une execution distante n'en a pas.
Un noeud `remote/<ticket>` par ticket recent (< 7 jours, ni clos ni archive) portant un run
`remote`, rattache a son parent comme un agent ordinaire."""
from __future__ import annotations

from types import SimpleNamespace

from ...sessions import category
from ..etat_ticket import vue_rattachee
from ..fsm import etats
from . import runs

_ETAT_PAR_VIVACITE = {"running": "running", "delivered": "finished", "crashed": "crashed"}


def _a_montrer(slug: str, ticket: dict, deja: set, project_by_slug: dict) -> dict | None:
    from .. import inbox
    if slug not in project_by_slug or str(ticket.get("id") or "") in deja:
        return None
    if ticket.get("state") in etats.CLOS or ticket.get("archived"):
        return None
    run = next((r for r in ticket.get("runs") or [] if runs.est_distant(r)), None)
    if run is None or not (runs.actif(run) or inbox._recent(str(run.get("started_at") or ""))):
        return None
    return run


def noeuds_distants(tous: list[tuple[str, dict]], par_ticket: dict, deja: set,
                    project_by_slug: dict) -> list[dict]:
    """`tous` = `_persistence.all_tickets()` deja lu par l'appelant (aucune lecture de plus)."""
    from .. import fleet, lexique
    noeuds = []
    for slug, ticket in tous:
        run = _a_montrer(slug, ticket, deja, project_by_slug)
        if run is None:
            continue
        vivacite = runs.vivacite(run)
        state = _ETAT_PAR_VIVACITE[vivacite]
        etat = lexique.etat_agent(state, vivacite)
        lien = par_ticket.get(str(ticket["id"])) or {}
        noeuds.append(fleet._synthetic_node(
            ticket, slug, project_by_slug[slug], key=f"remote/{ticket['id']}",
            agent_id=run["agent_id"], title=lien.get("titre") or ticket.get("title") or "Rundeck",
            isolated=False, state=state, liveness=vivacite, kind=runs.KIND,
            category=category.classify_agent(SimpleNamespace(
                agent_id=ticket["id"], prompt=ticket.get("prompt") or "", parent=ticket.get("parent") or "")),
            interrupted=vivacite == "crashed", saved_at=str(run.get("started_at") or ""),
            url=str(run.get("url") or ""), raison_arret=str(run.get("raison") or ""),
            etat=etat, libelle_etat=lexique.libelle_etat(etat),
            micro_id=lien.get("micro_id", ""), tache_titre=lien.get("titre", ""),
            **vue_rattachee(ticket)))
    return noeuds
