# [desc] Recensement de la flotte VIVANTE pour `GET /api/agents/activity` : une ligne par agent vivant et par ticket en lancement, rangées (attentes, silencieux, autres). Lit le store, aucun git. [/desc]
"""Extrait de `activity.py` : `report()` applique `activity.describe` (pur) au parc vivant.
`activity.report()` reste le point d'entrée historique et délègue ici."""
from __future__ import annotations

from . import etat_ticket
from .activity import children_index, describe


def _agents_vivants() -> list[tuple]:
    """(agent, statut) des seuls agents VIVANTS. Le statut d'abord (IPC + pid, quelques
    octets) ; la méta de session n'est lue ensuite que pour eux (le listing complet du parc
    coûtait 13,7 s à froid pour trois derniers outils)."""
    from ..sessions import store
    from ...runtime.runner import agent_registre
    vivants = []
    for agent in agent_registre.list_agents():
        status = store.agent_status(agent)
        if describe(status, {}):
            vivants.append((agent, status))
    return vivants


def _tickets_ouverts() -> dict[str, dict]:
    """Les tickets non clos, par id : l'état persisté que la ligne d'un agent rattache (L2)."""
    from . import tickets
    from .fsm import etats
    ouverts = tuple(e for e in etats.ETATS if e not in etats.CLOS)
    return {t["id"]: t for _, t in tickets.tickets_dans_les_etats(ouverts)}


def _ligne_agent(agent, status: dict, children: dict, meta_cache: dict,
                 ouverts: dict | None = None) -> dict:
    from ..sessions import store
    # Un enfant désigne son parent par l'un ou l'autre identifiant selon la voie de dispatch.
    cles = [agent.agent_id, getattr(agent, "ticket_id", "") or ""]
    waiting_for = next((children[k] for k in cles if k and k in children), None)
    return {
        "agent_id": agent.agent_id,
        "key": f"agent/{agent.agent_id}",
        "state": status.get("state", ""),
        # Phase de démarrage : la seule chose à dire d'un agent quand « en cours » est muet ;
        # elle rafraîchit la sidebar sans recalculer l'arbre (cf. `fleet_live`).
        "phase": status.get("phase", ""),
        "ticket_id": getattr(agent, "ticket_id", "") or "",
        "parent": agent.parent or "",
        "title": (agent.prompt or "").strip().split("\n")[0][:80],
        "question": status.get("question", ""),
        **describe(status, store.agent_meta(agent, meta_cache), waiting_for=waiting_for),
        **etat_ticket.vue_rattachee((ouverts or {}).get(getattr(agent, "ticket_id", "") or "")),
    }


def _ligne_lancement(slug: str, ticket: dict, project_names: dict) -> dict:
    from . import launch_phase
    phase = launch_phase.phase_view(ticket)
    return {
        "agent_id": "", "key": f"launching/{ticket['id']}",
        "state": "provisioning", "ticket_id": ticket["id"],
        "parent": ticket.get("parent") or "",
        "title": ticket.get("title") or "Nouvelle conversation",
        "project_name": project_names.get(slug, ""),
        # Un lancement n'a pas d'activité d'agent : sa phase EST son activité.
        "activity_label": phase.get("phase_label", "préparation en cours"),
        **phase,
        **etat_ticket.vue_rattachee(ticket),
    }


def _rang(row: dict) -> tuple:
    """Ceux qui attendent une réponse d'abord, puis les silencieux anormaux, puis les autres."""
    if row["state"].startswith("awaiting"):
        return 0, row["title"]
    return (1 if row.get("stale") else 2), row["title"]


def report() -> dict:
    """Recensement des agents VIVANTS et des tickets en cours de lancement, avec ce qu'ils font.

    La vue de surveillance bon marché : aucun subprocess git, aucun prompt, aucun agent
    terminé (l'arbre complet coûte ~9,5 s et 929 Ko pour une poignée de champs).

    DEUX PASSES : savoir qu'un parent attend exige de connaître ses enfants vivants, donc
    d'avoir déjà recensé tout le parc vivant. Un enfant encore en provisioning compte autant
    qu'un enfant démarré : son parent l'attend déjà."""
    from . import projects, tickets
    live_agents = _agents_vivants()
    project_names = {p["slug"]: p["name"] for p in projects.list_projects()}
    launching = list(tickets.launching_tickets())
    children = children_index(
        [(a.parent or "", getattr(a, "ticket_id", "") or a.agent_id) for a, _ in live_agents]
        + [(t.get("parent") or "", t.get("id") or "") for _, t in launching])
    meta_cache: dict = {}
    ouverts = _tickets_ouverts() if live_agents else {}
    rows = [_ligne_agent(agent, status, children, meta_cache, ouverts)
            for agent, status in live_agents]
    rows += [_ligne_lancement(slug, ticket, project_names) for slug, ticket in launching]
    rows.sort(key=_rang)
    return {"agents": rows, "count": len(rows),
            "awaiting": sum(1 for r in rows if r["state"].startswith("awaiting")),
            "stale": sum(1 for r in rows if r.get("stale"))}
