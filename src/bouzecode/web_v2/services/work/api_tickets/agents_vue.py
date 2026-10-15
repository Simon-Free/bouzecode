# [desc] GET /api/agents (liste PURE paginée, filtres state/parent/project), /api/agents/{id} (fiche) et /children : une seule vue des agents, filtrée par état (awaiting_input, unreachable, interrupted, stopped) ou par projet. [/desc]
"""Spec §6.4. Une ligne par agent du parc : `{agent_id, key, title, state, parent, project_slug,
ticket_slug, ticket_id, ticket_state…}` ; le relevé (état, question, projet) est CELUI de
l'arbre (`parc.releve`, une seule source), le ticket celui du store (`etat_ticket.vue_rattachee`).

Filtres `state` particuliers :
  * `awaiting_input` — question OU plan à valider, avec la question ;
  * `unreachable` — agents de tickets ouverts dont la fiche a disparu ;
  * `interrupted` — conversations interrompues par un arrêt du serveur, plus le rapport du
    dernier démarrage ;
  * `stopped` — agents dont le ticket est `stopped`.
Pagination par curseur (rang dans la liste triée, la plus récente en tête)."""
from __future__ import annotations

from ....runtime.runner import agent_fiche
from ...sessions import recovery
from .. import awaiting, enfants, etat_ticket, parc, projects, tickets
from ..fsm import etats
from .lectures import LIMITE_DEFAUT, LIMITE_MAX, _entier
from .refus import Refus

SPECIAUX = ("awaiting_input", "unreachable", "interrupted", "stopped")


def _index_tickets() -> dict[tuple[str, str], dict]:
    return {(slug, ticket["id"]): ticket for slug, ticket in tickets.all_tickets()}


def ligne(agent, index: dict, project_list: list[dict]) -> dict:
    """Le relevé COMMUN avec l'arbre (`parc.releve` : état, question, projet, ticket), plus ce
    que la liste ajoute : titre, cwd, état projeté du ticket."""
    ticket = index.get((agent.ticket_slug or "", agent.ticket_id or ""))
    titre = (getattr(agent, "titre", "") or (agent.prompt or "").strip().split("\n")[0])[:90]
    return {**parc.releve(agent, project_list), "title": titre or agent.agent_id,
            "ticket_slug": agent.ticket_slug or "", "cwd": agent.cwd or "",
            **etat_ticket.vue_rattachee(ticket)}


def _toutes() -> list[dict]:
    index, project_list = _index_tickets(), projects.list_projects()
    lignes = [ligne(a, index, project_list) for a in parc.collecter()]
    lignes.sort(key=lambda row: row["started_at"], reverse=True)
    return lignes


def _injoignables() -> list[dict]:
    return [{"agent_id": agent_id, "key": f"agent/{agent_id}", "state": "unreachable",
             "title": row["title"], "project_slug": row["project_slug"],
             "ticket_slug": row["project_slug"], "ticket_id": row["ticket_id"],
             "parent": "", "trash_dir": row["trash_dir"]}
            for row in awaiting.unreachable_ticket_agents() for agent_id in row["agent_ids"]]


def _filtrees(state: str) -> list[dict]:
    if state == "awaiting_input":
        return [{**row, "state": row["state"]} for row in awaiting.agents_awaiting_answer()]
    if state == "unreachable":
        return _injoignables()
    if state == "interrupted":
        return [{**row, "state": "interrupted"} for row in recovery.list_interrupted()]
    lignes = _toutes()
    if state == "stopped":
        return [row for row in lignes if row.get("ticket_state") == etats.STOPPED]
    return [row for row in lignes if not state or row["state"] == state]


def lister(state: str = "", parent: str = "", project: str = "", limit=None, cursor=None) -> dict:
    lignes = _filtrees(str(state or ""))
    if parent:
        lignes = [r for r in lignes if (r.get("parent") or "") in (parent, f"agent/{parent}")]
    if project:
        lignes = [r for r in lignes if project in (r.get("project_slug"), r.get("ticket_slug"))]
    debut = _entier(cursor, 0)
    taille = min(max(_entier(limit, LIMITE_DEFAUT), 1), LIMITE_MAX)
    suite = debut + taille if debut + taille < len(lignes) else None
    corps = {"agents": lignes[debut:debut + taille], "next_cursor": str(suite) if suite else None,
             "total": len(lignes)}
    if state == "interrupted":  # + le rapport figé au démarrage {boot_at, items}
        from .. import interrupted_report
        corps.update(interrupted_report.read_report())
    return corps


def connu(agent_id: str) -> bool:
    return agent_fiche.load_agent(agent_id) is not None or bool(enfants.tickets_enfants(agent_id))


def fiche(agent_id: str) -> dict:
    agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        raise Refus("agent_inconnu", f"agent inconnu : {agent_id}", 404, agent_id=agent_id)
    corps = ligne(agent, _index_tickets(), projects.list_projects())
    #  Un agent isolé en vol travaille hors du dossier du projet : sa fiche nomme quand même
    #  le projet (par le dépôt du worktree) — l'outil `Agent` de ses enfants le lit ici.
    corps["project_slug"] = corps["project_slug"] or projects.slug_of_agent(agent_id)
    ticket = tickets.get_ticket(agent.ticket_slug, agent.ticket_id) if agent.ticket_id else None
    run = next((r for r in (ticket or {}).get("runs") or [] if r.get("agent_id") == agent_id),
               None)
    return {**corps, "run": run, "children": enfants_de(agent_id)["children"]}


def enfants_de(agent_id: str) -> dict:
    if not connu(agent_id):
        raise Refus("agent_inconnu", f"agent inconnu : {agent_id}", 404, agent_id=agent_id)
    liste = enfants.enfants_de(agent_id)
    return {"agent_id": agent_id, "children": liste}
