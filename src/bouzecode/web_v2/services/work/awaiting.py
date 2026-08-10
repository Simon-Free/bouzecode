# [desc] Les agents bloqués sur une question posée à l'utilisateur, avec leur question. [/desc]
"""« Quels agents attendent une réponse de MA part ? » — une seule liste, sans lire un log.

Répondre à cette question demandait jusqu'ici de deviner : l'arbre de flotte ne portait
qu'un `state` noyé parmi 960 nœuds, `/api/conversations/stale-need-input` ne listait QUE
les attentes déjà mortes de vieillesse, et le texte de la question ne sortait nulle part.
Un manager a ainsi attendu plus d'une heure sans que rien ne le signale.

Ce module ne réinvente aucune règle : l'attente et son contenu viennent de
`store.agent_status`, seule source qui croise le process, l'état IPC et la question
pendante sur disque. On y ajoute ce qu'il faut pour AGIR : où répondre (projet, ticket)
et depuis quand on fait attendre l'agent.
"""
from __future__ import annotations

from ...runtime import runner
from ..sessions import store, visibility
from . import projects

# Les deux façons d'être bloqué sur un humain : une question libre (AskUserQuestion) ou
# une validation de plan (WritePlan user_validation_required).
AWAITING_STATES = ("awaiting_input", "awaiting_plan_validation")


def _row(agent: runner.Agent, status: dict, project_list: list[dict]) -> dict:
    project = projects.project_for_cwd(agent.cwd, project_list)
    return {
        "agent_id": agent.agent_id,
        "key": f"agent/{agent.agent_id}",
        "title": (agent.prompt or "").strip().split("\n")[0][:90] or agent.agent_id,
        "state": status["state"],
        # LA question, pas seulement son existence — c'est tout l'intérêt de la liste.
        "question": status.get("question", ""),
        "options": status.get("options") or [],
        # Vaut ici quelque chose : la réponse est-elle libre, ou limitée aux options ?
        "allow_freetext": bool(status.get("allow_freetext", True)),
        # Depuis quand on le fait attendre (date de la QUESTION, pas de l'agent).
        "asked_at": visibility.asked_at(agent),
        # Process encore debout : la réponse repart à chaud, sinon elle respawne l'agent.
        "warm": runner.is_running(agent),
        # Où répondre : POST /api/tickets/<slug>/<id>/comments (send=true), ou
        # POST /api/agents/<agent_id>/continue pour un agent sans ticket.
        "project_slug": project["slug"] if project else "",
        "ticket_slug": getattr(agent, "ticket_slug", "") or "",
        "ticket_id": getattr(agent, "ticket_id", "") or "",
        "parent": agent.parent or "",
    }


def unreachable_ticket_agents() -> list[dict]:
    """Les tickets OUVERTS qui référencent un agent dont l'enregistrement a disparu.

    Un agent sans fiche est INJOIGNABLE : `runner.load_agent` renvoie None, tout message
    vers lui échoue, il n'apparaît dans aucune liste d'agents — le ticket, lui, reste là.
    Ce trou ne se signalait nulle part : le ticket se lisait comme un banal « planté ».
    Chaque entrée dit QUI est introuvable et OÙ chercher sa fiche."""
    from . import liveness, projects as projets, tickets as tickets_service

    rows = []
    for project in projets.list_projects():
        for ticket in tickets_service.list_tickets(project["slug"]):
            if liveness.classify_ticket(ticket) != liveness.MISSING:
                continue
            introuvables = [
                run.get("agent_id") for run in (ticket.get("runs") or [])
                if isinstance(run, dict) and run.get("agent_id")
                and runner.load_agent(run["agent_id"]) is None
            ]
            rows.append({
                "project_slug": project["slug"],
                "ticket_id": ticket.get("id", ""),
                "title": ticket.get("title", ""),
                "agent_ids": introuvables,
                # Où sa fiche a le plus de chances d'être : la corbeille du parc.
                "trash_dir": str(runner.AGENTS_DIR / "_trash"),
            })
    return rows


def agents_awaiting_answer() -> list[dict]:
    """Tous les agents qui attendent une réponse humaine, question comprise.

    Un agent ARCHIVÉ qui attend reste dans la liste : le drapeau d'archivage ne peut pas
    faire taire une question sans réponse (c'est précisément ce qui rendait l'attente
    introuvable). Les conversations de test, elles, sont écartées.

    Tri : la plus ancienne question d'abord — celle qu'on fait attendre depuis le plus
    longtemps est celle à traiter en premier."""
    from ..sessions import category

    project_list = projects.list_projects()
    rows = []
    for agent in runner.list_agents():
        if category.classify_agent(agent) == category.CATEGORY_TEST:
            continue
        status = store.agent_status(agent)
        if status.get("state") not in AWAITING_STATES:
            continue
        rows.append(_row(agent, status, project_list))
    rows.sort(key=lambda row: row["asked_at"] or row["agent_id"])
    return rows
