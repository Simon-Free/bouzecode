# [desc] Parc d'agents tous projets confondus, groupé par manager (parent). [/desc]
"""Vue cross-projet : chaque agent web avec son projet, son état et son parent.

Le groupement par parent (agent manager, "dispatcher:manual", ou "") est laissé
au front. `suspect_dead` repère les vrais morts anormaux : fini sans aucun tour
ET avec un returncode non nul (ou absent). Un agent fini avec rc=0 est un succès
propre — il n'est JAMAIS suspect, même à 0 tour.

Trois sortes de nœuds :
- les agents (`agent/<id>`), construits par `_node` ;
- les tickets en cours de lancement (`launching/<ticket>`) : aucun agent n'existe encore,
  mais la conversation doit apparaître tout de suite avec la phase en cours ;
- les lancements échoués récents (`failed/<ticket>`), ajoutés par `habiller`.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from bouzecode.web_v2.services.horodatage import cle_chrono

from ..sessions import empreintes, purge, store, visibility
from . import _tree_page, fleet_cache, fleet_live, fleet_vue, liveness, parc, projects  # noqa: F401
from .etat_ticket import vue_rattachee
# Façade : les nœuds et le façonnage de l'arbre vivent dans `fleet_noeuds` / `fleet_arbre` ;
# terminer des process vit dans `warm_pool` (une lecture de l'arbre ne tue jamais un agent).
from .fleet_arbre import (  # noqa: F401 — ré-export
    _awaiting_rank_and_recency, _etat_du_noeud, _habiller_noeud, _inherit_recap, _prewarm_git,
    _propagate_liveness, _sort_nodes,
)
from .fleet_noeuds import (  # noqa: F401 — ré-export
    _launching_node, _launching_nodes, _node, _noeuds_lancement_echoue, _repo_fields,
    _short_label, _suspect_dead, _synthetic_node,
)
from .warm_pool import WARM_POOL_MAX, sweep_warm_pool  # noqa: F401 — ré-export façade

_log = logging.getLogger(__name__)

# ------------------------------------------------------------------ l'arbre


def agent_tree(offset: int = 0, limit: int | None = None,
               avec_git: bool = True, attendre: bool = False) -> dict[str, Any]:
    """Page de racines de l'arbre (chacune avec tous ses sous-agents). Sans `limit`, l'arbre
    complet.

    SERVIR D'ABORD, RECALCULER ENSUITE (`fleet_cache`) : une entrée périmée est rendue telle
    quelle et le recalcul part en fond ; seul le tout premier appel d'une clé attend. L'arbre
    est une vue d'observation : une seconde de retard sur un statut est sans conséquence, une
    interface figée plusieurs secondes l'est. La PHASE et l'activité, elles, sont relues à
    chaque lecture par-dessus la page mémorisée (`fleet_live`).

    Chaque page servie est notée dans `fleet_vue` (dernier état MONTRÉ de chaque agent : la
    pastille « en cours » le compte). `attendre` : une page périmée est recalculée avant d'être
    servie (recalcul de fond des pastilles, jamais une requête de l'interface)."""
    lire = fleet_cache.compute_and_store if attendre else fleet_cache.cached
    page = lire(
        ("agent_tree", offset, limit, avec_git),
        lambda: {**_agent_tree_uncached(offset, limit, avec_git), "_calcule_a": time.monotonic()},
    )
    vue = habiller(fleet_live.overlay(page))  # copie : la page du cache n'est jamais modifiée
    calcule_a = vue.pop("_calcule_a", None)
    if calcule_a is not None:
        fleet_vue.noter(vue.get("nodes") or [], calcule_a, complet=offset == 0 and limit is None)
    return vue


_pastille_en_fond = threading.Lock()


def agents_au_travail() -> int:
    """Pastille « en cours » : les agents que l'ARBRE SERVI montre au travail (`fleet_vue`),
    jamais un second calcul. Sert aussitôt ; si aucune page complète n'a été servie depuis
    `fleet_cache.TTL_SECONDS`, en recalcule une en fond (sans git) pour le poll suivant."""
    age = fleet_vue.age_complet()
    if age is None:
        agent_tree(avec_git=False)
    elif age > fleet_cache.TTL_SECONDS and _pastille_en_fond.acquire(blocking=False):
        threading.Thread(target=_rafraichir_la_pastille, name="pastilles-arbre", daemon=True).start()
    return fleet_vue.au_travail()


def _rafraichir_la_pastille() -> None:
    try:
        agent_tree(avec_git=False, attendre=True)
    except Exception:  # noqa: BLE001 — la pastille garde son compte jusqu'au prochain essai
        _log.debug("pastille en cours : arbre illisible", exc_info=True)
    finally:
        _pastille_en_fond.release()


def habiller(page: dict) -> dict:
    """Ajoute à chaque nœud le lexique UI (`etat`, `libelle_etat`) et sa tâche du Bureau
    (`micro_id`, `tache_titre`), puis les lancements échoués récents (`failed/<ticket>`).

    Ne modifie JAMAIS la page reçue (elle vient d'un cache partagé) : nœuds recopiés."""
    from . import micros as micros_service
    try:
        par_ticket = micros_service.micro_par_ticket()
    except Exception:  # noqa: BLE001 — la base des tâches ne doit pas casser l'arbre
        par_ticket = {}
    from . import _persistence
    from .distant.noeuds import noeuds_distants
    tous = _persistence.all_tickets()  # UNE lecture : état des tickets + nœuds synthétiques
    par_id = {str(t.get("id")): t for _slug, t in tous}
    #  L'état du TICKET est relu à chaque lecture (jamais celui de la page mémorisée) : l'arbre
    #  dit le même `ticket_state` / `libelle_ticket` que la fiche et la liste (critère 2).
    noeuds = [{**_habiller_noeud(node, par_ticket),
               **vue_rattachee(par_id.get(str(node.get("ticket_id") or "")))}
              for node in page.get("nodes") or []]
    project_by_slug = {p["slug"]: p for p in projects.list_projects()}
    deja = {n.get("ticket_id") for n in noeuds}
    noeuds.extend(_noeuds_lancement_echoue(tous, par_ticket, deja, project_by_slug))
    noeuds.extend(noeuds_distants(tous, par_ticket, deja, project_by_slug))  # exécutions Rundeck
    return {**page, "nodes": noeuds}


def archived_tree() -> dict:
    """Les conversations ARCHIVÉES (cachées de l'arbre), pour le groupe « Archivés »."""
    from . import lexique
    project_list = projects.list_projects()
    meta_by_key = {a["key"]: a for a in store.list_agent_sessions(include_tests=True)}
    deleted = purge.load_deleted()
    noeuds = []
    for agent in parc.collecter():
        if not visibility.hidden_by_archive(agent, deleted):
            continue
        node = _node(agent, meta_by_key.get(f"agent/{agent.agent_id}", {}), project_list)
        node.update(etat="archived", libelle_etat=lexique.libelle_etat("archived"),
                    archived=True)
        noeuds.append(node)
    noeuds.sort(key=lambda n: cle_chrono(n.get("saved_at") or n.get("started_at")), reverse=True)
    return {"nodes": noeuds, "total_roots": len(noeuds)}


def clear_tree_cache() -> None:
    """Oublie l'arbre mémorisé : le prochain appel rend la photo de MAINTENANT (tests)."""
    fleet_cache.clear()


def _visible_agents() -> list:
    """Agents non archivés — sauf ceux encore vivants : un agent qui tourne ou attend une
    réponse reste visible quoi qu'il arrive (cf. sessions/visibility.py)."""
    return parc.collecter(visibles_seulement=True)


def _agent_tree_uncached(offset: int = 0, limit: int | None = None,
                         avec_git: bool = True) -> dict[str, Any]:
    """Les agents web, à plat, avec parent/projet/état (le front groupe).

    Avec `limit`, seules `limit` racines à partir d'`offset` (et leurs descendants) sont
    CONSTRUITES : les infos git, qui dominent le coût, ne sont payées que sur les nœuds servis.
    `total_roots` ne compte que les racines agents : les nœuds de lancement, peu nombreux et
    sans coût git, sont servis sur toutes les pages."""
    project_list = projects.list_projects()
    meta_by_key = {a["key"]: a for a in store.list_agent_sessions()}
    agents = _visible_agents()
    roots = _tree_page.roots_in_display_order(
        agents, lambda agent: _awaiting_rank_and_recency(
            agent, meta_by_key.get(f"agent/{agent.agent_id}", {})))
    if limit is not None:
        agents = _tree_page.with_descendants(roots[offset:offset + limit], agents)
    if avec_git:
        _prewarm_git(agents)
    nodes = [_node(agent, meta_by_key.get(f"agent/{agent.agent_id}", {}), project_list,
                   avec_git=avec_git)
             for agent in agents]
    _inherit_recap(nodes)
    _propagate_liveness(nodes)
    nodes.extend(_launching_nodes(project_list, {n["ticket_id"] for n in nodes if n.get("ticket_id")}))
    _sort_nodes(nodes)
    #  Clôtures lues pour classer les agents morts : une seule écriture de leurs empreintes.
    empreintes.ecrire_tout()
    return {"nodes": nodes, "total_roots": len(roots)}
