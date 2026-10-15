# [desc] Archivage en cascade d'une tâche classée (tickets + conversations d'agents, sous-agents compris) et restauration à la réouverture. [/desc]
"""Classer une tâche (« faite » ou « abandonnée ») archive ce qu'elle a produit ; la rouvrir
le ramène (SPEC §4.6).

* **Tout est réversible** : les tickets reçoivent le drapeau `archived` (jamais retirés du
  store) et les conversations passent au registre de soft-delete, comme l'archivage manuel.
* **Provenance** : chaque archivage porte l'étiquette `tache:<id>` (champ `archived_by` du
  ticket, raison du registre). Rouvrir ne restaure QUE ce qui porte cette étiquette : un
  ticket ou une conversation que l'utilisateur avait archivé à la main reste archivé.
* **Idempotent** : reclasser ou rouvrir deux fois ne compte ni n'archive rien de plus.
* **Erreurs partielles** : un ticket introuvable n'empêche pas les autres ; il est rapporté.
"""
from __future__ import annotations


def etiquette(micro_id: str) -> str:
    return f"tache:{micro_id}"


def _liens(micro: dict) -> list[tuple[str, str]]:
    return [(str(l.get("slug") or ""), str(l["ticket_id"]))
            for l in (micro.get("tickets") or []) if l.get("ticket_id")]


def _agents_des_runs(ticket: dict) -> list[str]:
    return [str(r["agent_id"]) for r in ticket.get("runs") or []
            if isinstance(r, dict) and r.get("agent_id")]


def _enfants_par_parent() -> dict[str, list[str]]:
    from bouzecode.web_v2.runtime.runner import agent_registre
    enfants: dict[str, list[str]] = {}
    for agent in agent_registre.list_agents():
        if agent.parent:
            enfants.setdefault(agent.parent, []).append(agent.agent_id)
    return enfants


def _avec_descendants(racines: list[str]) -> list[str]:
    """Les agents donnés et tout leur sous-arbre (sous-agents, sous-sous-agents…)."""
    enfants = _enfants_par_parent()
    vus: list[str] = []
    pile = list(racines)
    while pile:
        agent_id = pile.pop()
        if agent_id in vus:
            continue
        vus.append(agent_id)
        pile.extend(enfants.get(agent_id, []))
    return vus


def _archiver_tickets(liens, tag: str) -> tuple[int, list[str], list[dict]]:
    """(tickets nouvellement archivés, agents de TOUS les tickets, erreurs)."""
    from . import tickets as tickets_service
    archives, agents, erreurs = 0, [], []
    for slug, ticket_id in liens:
        ticket = tickets_service.get_ticket(slug, ticket_id)
        if ticket is None:
            erreurs.append({"ticket_id": ticket_id, "error": "ticket introuvable"})
            continue
        agents.extend(_agents_des_runs(ticket))
        if not ticket.get("archived"):
            tickets_service.archive_ticket(slug, ticket_id, par=tag)
            archives += 1
    return archives, agents, erreurs


def _archiver_conversations(agent_ids: list[str], tag: str) -> int:
    from ..sessions import purge
    deja = purge.load_deleted()
    nouvelles = [f"agent/{a}" for a in agent_ids if f"agent/{a}" not in deja]
    for key in nouvelles:
        purge.mark_deleted(key, reason=tag)
    return len(nouvelles)


def _rafraichir() -> None:
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from . import fleet, taches_vue
    agent_fiche._list_agents_cache.clear()
    fleet.clear_tree_cache()
    taches_vue.invalider()


def archiver(micro: dict) -> dict:
    """Archive les tickets de la tâche et les conversations de leurs agents (+ sous-agents)."""
    tag = etiquette(micro["id"])
    tickets, agents, erreurs = _archiver_tickets(_liens(micro), tag)
    conversations = _archiver_conversations(_avec_descendants(agents), tag) if agents else 0
    _rafraichir()
    bilan = {"tickets": tickets, "conversations": conversations}
    return {**bilan, **({"erreurs": erreurs} if erreurs else {})}


def _restaurer_tickets(liens, tag: str) -> int:
    from . import tickets as tickets_service
    restaures = 0
    for slug, ticket_id in liens:
        ticket = tickets_service.get_ticket(slug, ticket_id)
        if ticket and ticket.get("archived") and ticket.get("archived_by") == tag:
            tickets_service.unarchive_ticket(slug, ticket_id)
            restaures += 1
    return restaures


def _restaurer_conversations(tag: str) -> int:
    from ..sessions import purge
    cles = [k for k, v in purge.load_deleted().items()
            if isinstance(v, dict) and v.get("reason") == tag]
    return sum(1 for key in cles if purge.restore(key))


def restaurer(micro: dict) -> dict:
    """Ramène ce que `archiver` a archivé pour cette tâche, et seulement cela."""
    tag = etiquette(micro["id"])
    bilan = {"tickets": _restaurer_tickets(_liens(micro), tag),
             "conversations": _restaurer_conversations(tag)}
    _rafraichir()
    return bilan
