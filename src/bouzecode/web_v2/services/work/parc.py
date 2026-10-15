# [desc] LA collecte du parc d'agents et le relevé commun d'un agent (état, question, projet, ticket) : une seule source pour GET /api/agents (`api_tickets/agents_vue`) et GET /api/agents/tree (`fleet`). [/desc]
"""Les deux vues du parc lisaient chacune les agents et dérivaient chacune état, question et
projet : deux vérités possibles sur le même agent (spec ticketing §10, critère 2). Elles partent
désormais de `collecter` (quels agents) et de `releve` (ce qu'on sait de chacun) ; chaque vue
n'ajoute que ce qui lui est propre (titre, arbre, vivacité propagée, git…)."""
from __future__ import annotations

from ...runtime.runner import agent_registre
from ..sessions import purge, store, visibility
from . import projects

AWAITING = ("awaiting_input", "awaiting_plan_validation")


def collecter(visibles_seulement: bool = False) -> list:
    """Les agents du parc. `visibles_seulement` : sans les archivés — sauf un agent encore
    vivant, qui reste visible quoi qu'il arrive (cf. sessions/visibility.py)."""
    agents = agent_registre.list_agents()
    if not visibles_seulement:
        return agents
    deleted = purge.load_deleted()
    return [a for a in agents if not visibility.hidden_by_archive(a, deleted)]


def champs_question(status: dict) -> dict:
    """La question en attente, seulement si l'agent attend une réponse. `allow_freetext` n'est
    servi QUE face à une question : présent partout, il ressemblait à un signal sans en porter."""
    if status.get("state", "") not in AWAITING:
        return {"question": "", "options": []}
    return {"question": status.get("question", ""), "options": status.get("options") or [],
            "allow_freetext": bool(status.get("allow_freetext", True))}


def projet_de(agent, project_list: list[dict]) -> dict:
    """{project_slug, project_name} : le projet du ticket de l'agent, sinon celui de son cwd."""
    projet = projects.project_for_cwd(agent.cwd, project_list) or {}
    slug = getattr(agent, "ticket_slug", "") or projet.get("slug", "")
    nom = projet.get("name", "") if projet.get("slug") == slug else next(
        (p["name"] for p in project_list if p["slug"] == slug), "")
    return {"project_slug": slug, "project_name": nom}


def releve(agent, project_list: list[dict], status: dict | None = None) -> dict:
    """Ce que les deux vues disent de la même façon d'un agent : identité, parent, état et phase
    (`store.agent_status`), question en attente, projet, ticket, démarrage."""
    status = status or store.agent_status(agent)
    return {"agent_id": agent.agent_id, "key": f"agent/{agent.agent_id}",
            "parent": agent.parent or "", "state": status.get("state", ""),
            "phase": status.get("phase", ""), **champs_question(status),
            **projet_de(agent, project_list),
            "ticket_id": getattr(agent, "ticket_id", "") or "",
            "started_at": agent.started_at or ""}
