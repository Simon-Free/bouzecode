# [desc] Découpe de l'arbre d'agents en pages de RACINES (logique pure, sans I/O). [/desc]
"""Sélection paginée des racines servies par `/api/agents/tree`.

Le front (`static/js/conversations.js`) demande `limit` RACINES à partir d'`offset`
et compte sur le serveur pour joindre à chaque racine TOUS ses descendants — une
racine servie sans ses sous-agents afficherait un manager vide. Isoler la sélection
ici garde `fleet.py` sur son métier (construire les nodes) et rend la pagination
testable sans agent réel ni sous-process git.

Racine = agent dont le `parent` ne désigne AUCUN agent présent : parent vide,
"dispatcher:manual", ou parent disparu de l'arbre (archivé/purgé). C'est exactement
la définition qu'applique le front. Le `parent` est stocké tantôt en id nu, tantôt
en clé "agent/<id>" : les deux formes sont indexées.
"""
from __future__ import annotations

from typing import Callable


def _refs(agent_id: str) -> tuple[str, str]:
    """Les deux écritures sous lesquelles un agent peut être référencé par un enfant."""
    return agent_id, f"agent/{agent_id}"


def roots_in_display_order(agents: list, sort_key: Callable[[object], tuple[int, str]]) -> list:
    """Les racines, dans l'ordre d'affichage du front : awaiting_* en tête, puis récence.

    `sort_key(agent)` renvoie `(rang_attente, récence)` — même couple que le tri de
    la liste complète, pour que la page 1 contienne bien les conversations qui
    attendent une action de l'utilisateur."""
    present = {ref for agent in agents for ref in _refs(agent.agent_id)}
    roots = [agent for agent in agents if (agent.parent or "").strip() not in present]
    # Deux tris STABLES successifs, comme la liste complète : récence décroissante,
    # puis remontée des conversations en attente sans casser l'ordre interne.
    roots.sort(key=lambda agent: sort_key(agent)[1], reverse=True)
    roots.sort(key=lambda agent: sort_key(agent)[0])
    return roots


def with_descendants(selected_roots: list, agents: list) -> list:
    """Les racines choisies + TOUS leurs descendants, dans l'ordre de `agents`.

    Un sous-arbre est clos : les propagations qui remontent les chaînes parent
    (héritage du récap, statut « en cours » hiérarchique) restent donc exactes sur
    une page. Tolère les cycles de `parent` (garde sur les agents déjà retenus)."""
    children_by_ref: dict[str, list] = {}
    for agent in agents:
        parent = (agent.parent or "").strip()
        if parent:
            children_by_ref.setdefault(parent, []).append(agent)
    kept: set[str] = set()
    queue = list(selected_roots)
    while queue:
        agent = queue.pop()
        if agent.agent_id in kept:
            continue
        kept.add(agent.agent_id)
        for ref in _refs(agent.agent_id):
            queue.extend(children_by_ref.get(ref, ()))
    return [agent for agent in agents if agent.agent_id in kept]
