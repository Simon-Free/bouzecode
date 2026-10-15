# [desc] API flotte : arbre des agents (servi au front de la page Agents) et activité des agents vivants. Le lancement et les messages sont dans `routes/tickets_api`. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...services.work import activity, fleet

fleet_bp = Blueprint("fleet_api", __name__)


@fleet_bp.get("/api/agents/tree")
def api_agent_tree():
    """parc d'agents tous projets, en arbre parent/enfants ; les conversations en attente d'input
    remontent en tête. ?offset=&limit= sert `limit` RACINES (+ `total_roots`) ; ?archived=1
    liste les archivées. Chaque nœud porte `etat`/`libelle_etat` (lexique SPEC §1.1),
    `micro_id`/`tache_titre` (tâche du Bureau liée) ; nœuds synthétiques `launching/<ticket>`
    (préparation) et `failed/<ticket>` (lancement échoué, `launch_error`)."""
    if (request.args.get("archived") or "") in ("1", "true"):
        return jsonify(_titres_bornes(fleet.archived_tree()))
    offset = max(_int_arg("offset", 0), 0)
    limit = _int_arg("limit", 0)
    return jsonify(_titres_bornes(
        fleet.agent_tree(offset=offset, limit=limit if limit > 0 else None)))


#  `title_full` porte le PROMPT ENTIER de l'agent : mesuré sur les vraies données, 1542 Ko
#  des 2005 Ko servis (77 %), alors que le front n'en fait qu'une infobulle et la ligne
#  « sujet » (static/js/conversations/sidebar/group_update.js). On le BORNE dans la réponse,
#  jamais dans le service : le cache d'`agent_tree` est partagé (inbox le consomme aussi),
#  et le muter servirait un arbre amputé au consommateur suivant.
TITLE_FULL_MAX = 160
#  Clés produites par le service (l'inbox en dépend) mais JAMAIS lues par le front
#  (0 occurrence dans static/js + templates, vérifié) : la ROUTE ne les sert pas.
CLES_HORS_UI = ("idle_seconds", "last_event_at", "vivacite_propre", "raison_arret")


def _titres_bornes(payload: dict) -> dict:
    nodes = payload.get("nodes") or []
    if not nodes:
        return payload
    return {**payload,
            "nodes": [{**{c: v for c, v in n.items() if c not in CLES_HORS_UI},
                       "title_full": (n.get("title_full") or "")[:TITLE_FULL_MAX]}
                      for n in nodes]}


@fleet_bp.get("/api/agents/activity")
def api_agents_activity():
    """CE QUE FAIT chaque agent vivant : outil en cours, tour, âge du dernier battement
    (`idle_seconds`), silence anormal (`stale`), question posée — plus les tickets en cours de
    lancement avec leur phase (création du worktree / installation uv / démarrage). Vue de
    SURVEILLANCE : aucun git, aucun prompt, aucun agent terminé. À PRÉFÉRER à /api/agents/tree
    pour du monitoring — l'arbre complet coûte ~9,5 s et 929 Ko.

    Vue de SURVEILLANCE, taillée pour être appelée souvent : aucun subprocess git, aucun
    prompt, aucun agent terminé. À préférer à /api/agents/tree pour du monitoring — l'arbre
    complet coûte ~9,5 s et 929 Ko parce qu'il sert le parc entier avec ses infos git."""
    return jsonify(activity.report())


def _int_arg(name: str, default: int) -> int:
    """Paramètre de requête entier ; une valeur absente ou non numérique vaut `default`."""
    raw = (request.args.get(name) or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else default
