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

from ...runtime.runner import agent_fiche, agent_registre, agent_vivacite
from ..sessions import category, store, visibility
from . import projects

# Les deux façons d'être bloqué sur un humain : une question libre (AskUserQuestion) ou
# une validation de plan (WritePlan user_validation_required).
AWAITING_STATES = ("awaiting_input", "awaiting_plan_validation")


def _row(agent: agent_fiche.Agent, status: dict, project_list: list[dict]) -> dict:
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
        "warm": agent_vivacite.is_running(agent),
        # Où répondre : POST /api/projects/<slug>/tickets/<id>/answer (ou …/messages), ou
        # POST /api/agents/<agent_id>/messages pour un agent sans ticket.
        "project_slug": project["slug"] if project else "",
        "ticket_slug": getattr(agent, "ticket_slug", "") or "",
        "ticket_id": getattr(agent, "ticket_id", "") or "",
        "parent": agent.parent or "",
        # Nature de la conversation : la sonnette n'annonce jamais une conversation de test,
        # et c'est ici qu'elle l'apprend (elle ne voit que la row, pas l'agent).
        "category": category.classify_agent(agent),
    }


def unreachable_ticket_agents() -> list[dict]:
    """Les tickets OUVERTS qui référencent un agent dont l'enregistrement a disparu.

    Un agent sans fiche est INJOIGNABLE : `runner.load_agent` renvoie None, tout message
    vers lui échoue, il n'apparaît dans aucune liste d'agents — le ticket, lui, reste là.
    Ce trou ne se signalait nulle part : le ticket se lisait comme un banal « planté ».
    Chaque entrée dit QUI est introuvable et OÙ chercher sa fiche."""
    from . import etat_ticket, projects as projets, tickets as tickets_service
    from .fsm import etats

    rows = []
    for project in projets.list_projects():
        for ticket in tickets_service.list_tickets(project["slug"]):
            # Constaté par le watchdog (`constats`) : `stopped{introuvable}`, jamais redérivé.
            if not (ticket.get("state") == etats.STOPPED
                    and etat_ticket.code_raison(ticket) == "introuvable"):
                continue
            introuvables = [
                run.get("agent_id") for run in (ticket.get("runs") or [])
                if isinstance(run, dict) and run.get("agent_id")
                and agent_fiche.load_agent(run["agent_id"]) is None
            ]
            rows.append({
                "project_slug": project["slug"],
                "ticket_id": ticket.get("id", ""),
                "title": ticket.get("title", ""),
                "agent_ids": introuvables,
                # Où sa fiche a le plus de chances d'être : la corbeille du parc.
                "trash_dir": str(agent_fiche.AGENTS_DIR / "_trash"),
            })
    return rows


def _sans_archivees(rows: list[dict]) -> list[dict]:
    """Écarte les questions d'agents ARRÊTÉS que l'humain a classées sans réponse.

    Un agent vivant n'est jamais filtré : sa question reste visible et la réponse part."""
    if not rows:
        return rows
    from . import decisions
    try:
        classees = decisions.archived_questions()
    except Exception:  # noqa: BLE001 — base illisible : mieux vaut trop montrer que cacher
        return rows
    return [r for r in rows
            if r.get("warm") or (r["agent_id"], r.get("asked_at") or "") not in classees]


def archive_stopped_question(agent_id: str, comment: str = "") -> dict:
    """Classe sans réponse la question d'un agent arrêté. Refus si l'agent vit ou n'attend pas."""
    from . import decisions
    from .api_tickets.refus import Refus
    row = next((r for r in agents_awaiting_answer(include_archived=True)
                if r["agent_id"] == agent_id), None)
    if row is None:
        raise Refus("not_waiting", f"l'agent {agent_id} n'attend aucune réponse : rien à "
                    "classer.", 404, agent_id=agent_id)
    if row.get("warm"):
        raise Refus("agent_alive", f"l'agent {agent_id} est vivant et attend ta réponse : "
                    "réponds-lui plutôt que de classer sa question.", 409, agent_id=agent_id)
    return decisions.archive_question(agent_id, row.get("asked_at") or "", comment)


def agents_awaiting_answer(include_archived: bool = False) -> list[dict]:
    """Tous les agents qui attendent une réponse humaine, question comprise.

    Un agent ARCHIVÉ qui attend reste dans la liste : le drapeau d'archivage ne peut pas
    faire taire une question sans réponse (c'est précisément ce qui rendait l'attente
    introuvable). Les conversations de test, elles, sont écartées.

    Tri : la plus ancienne question d'abord — celle qu'on fait attendre depuis le plus
    longtemps est celle à traiter en premier."""
    project_list = projects.list_projects()
    rows = []
    for agent in agent_registre.list_agents():
        if category.classify_agent(agent) == category.CATEGORY_TEST:
            continue
        status = store.agent_status(agent)
        if status.get("state") not in AWAITING_STATES:
            continue
        rows.append(_row(agent, status, project_list))
    if not include_archived:
        rows = _sans_archivees(rows)
    rows.sort(key=lambda row: row["asked_at"] or row["agent_id"])
    return rows
