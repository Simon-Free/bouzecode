# [desc] Façonnage de l'arbre des agents : tri (attente d'abord, puis récence), caches git préchauffés, récap hérité par le manager, vivacité propagée aux ancêtres, lexique UI d'un nœud. [/desc]
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from bouzecode.web_v2.services.horodatage import cle_chrono

from ..sessions import store
from . import liveness, parc, repos

_AWAITING = parc.AWAITING


def _awaiting_rank_and_recency(agent, meta: dict) -> tuple[int, str]:
    """Clé de tri d'une racine : 0 si elle attend une réponse user, puis sa récence."""
    status = meta.get("status") or store.agent_status(agent)
    rank = 0 if status.get("state", "") in _AWAITING else 1
    return rank, (meta.get("saved_at") or agent.started_at or "")


def _prewarm_git(agents: list) -> None:
    """Remplit en parallèle les caches git (repo_key, branch_of) des cwd uniques : `_node`
    les lit ensuite sans lancer de sous-process (en série, ~1000 agents coûtaient 2 min+)."""
    unique_cwds = {agent.cwd for agent in agents if agent.cwd}
    if not unique_cwds:
        return
    with ThreadPoolExecutor(max_workers=min(32, len(unique_cwds))) as pool:
        for cwd in unique_cwds:
            pool.submit(repos.repo_key, cwd)
            pool.submit(repos.branch_of, cwd)


def _inherit_recap(nodes: list[dict]) -> None:
    """Un manager porte la pastille « Récap » dès qu'un de ses enfants a un récap : sa vue
    /recap concatène ceux des sous-agents."""
    recap_parents = {n["parent"] for n in nodes if n["has_recap"] and n["parent"]}
    for n in nodes:
        if n["agent_id"] in recap_parents or n["key"] in recap_parents:
            n["has_recap"] = True


def _propagate_liveness(nodes: list[dict]) -> None:
    """Un ancêtre est « en cours » tant qu'un de ses descendants vit (tourne ou attend une
    réponse). `liveness` de `_node` ne regarde que l'agent lui-même. Un ancêtre qui attend
    LUI-MÊME une réponse garde son état : c'est l'information la plus actionnable. Le `parent`
    est stocké en id nu OU en clé, d'où le double index."""
    by_ref = {**{n["agent_id"]: n for n in nodes}, **{n["key"]: n for n in nodes}}
    for node in nodes:
        node["vivacite_propre"] = node["liveness"]
    for node in nodes:
        if node["vivacite_propre"] in liveness.ALIVE:
            _mark_ancestors_running(node, by_ref, _actif(node))


def _actif(node: dict) -> bool:
    """Le nœud TRAVAILLE (un agent chaud mais oisif ne compte pas, un agent qui attend la réponse
    de l'utilisateur non plus : il est dans « À traiter », et son parent fini n'est pas « en
    cours »)."""
    return node["vivacite_propre"] == "running" and node.get("state") not in ("idle", *_AWAITING)


def _mark_ancestors_running(node: dict, by_ref: dict, actif: bool) -> None:
    seen: set[str] = set()
    parent_ref = node["parent"]
    while parent_ref and parent_ref not in seen:
        seen.add(parent_ref)
        ancestor = by_ref.get(parent_ref)
        if ancestor is None:
            return
        if ancestor["liveness"] not in liveness.ALIVE:
            ancestor["liveness"] = "running"
        if actif:
            ancestor["sous_agents_actifs"] = True
        parent_ref = ancestor["parent"]


def _sort_nodes(nodes: list[dict]) -> None:
    """Dernière interaction d'abord, puis (tri stable) les conversations en attente en tête."""
    nodes.sort(key=lambda n: cle_chrono(n.get("saved_at") or n["started_at"]), reverse=True)
    nodes.sort(key=lambda n: 0 if n["state"] in _AWAITING else 1)


def _etat_du_noeud(node: dict) -> str:
    """Clé du lexique SPEC §1.1 pour un nœud (cf. `lexique.etat_agent`).

    « Attend ses sous-agents » exige une PREUVE : un descendant réellement actif, posé par
    `_propagate_liveness`. Un enfant fini, oisif (warm pool) ou mort ne compte pas."""
    from . import lexique
    state = str(node.get("state") or "")
    vivacite = str(node.get("liveness") or "")
    enfants = state in ("finished", "cli", "idle") and bool(node.get("sous_agents_actifs"))
    if enfants:
        vivacite = ""
    elif state == "finished" and node.get("vivacite_propre") == "running":
        state = "running"  # son PROPRE process travaille : l'état de session est en retard
    return lexique.etat_agent(state, vivacite, str(node.get("phase") or ""), enfants)


def _habiller_noeud(node: dict, par_ticket: dict) -> dict:
    from . import lexique
    etat = _etat_du_noeud(node)
    lien = par_ticket.get(str(node.get("ticket_id") or "")) or {}
    libelle = lexique.libelle_etat(etat)
    if etat == "finished" and node.get("integre"):
        libelle = lexique.LEXIQUE["integre"]["mot"]
    habille = {**node, "etat": etat, "libelle_etat": libelle,
               "micro_id": lien.get("micro_id", ""), "tache_titre": lien.get("titre", "")}
    #  Un agent lancé depuis une tâche s'appelle comme SA tâche, pas comme la 1re ligne de
    #  son prompt assemblé.
    if lien.get("titre") and (node.get("kind") or "work") == "work":
        habille["title"] = str(lien["titre"])[:60]
    return habille
