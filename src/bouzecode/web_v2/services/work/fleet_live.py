# [desc] Rafraîchit à CHAQUE lecture les champs volatils (phase, activité) des nodes vivants d'une page d'arbre. [/desc]
"""Ce qui change vite, servi vite — sans recalculer ce qui change lentement.

LE DÉFAUT, mesuré le 2026-08-04 sur le parc réel (324 agents) et sur un vrai lancement :
`store.demarrage_phase` connaissait « le modèle lit votre demande » à t+7,94 s ; le badge de
la sidebar, qui lit `/api/agents/tree`, ne l'a montré qu'à t+14,50 s — **6,56 s de retard**,
et l'état intermédiaire `idle` n'a JAMAIS été affiché. La cause n'est pas le calcul : c'est
que la phase voyage dans une page mémorisée par `fleet_cache` pour 10 s. Le CORPS de la
conversation, lui, était déjà à 1,5 s — il lit `status.phase` servi par `/blocks`.

POURQUOI PAS DE BAISSER LE TTL. Mesuré sur le serveur qui tournait, sous-caches chaudes :
recalculer la page servie au front (12 racines) coûte **160-235 ms** (médiane 212 ms), contre
2-25 ms pour la resservir. Ramener le TTL sous la cadence de talonnage (1 s) reviendrait donc
à brûler ~21 % d'un cœur en permanence pendant chaque démarrage, pour rafraîchir ~40 nodes
dont un seul bouge. Recenser les agents VIVANTS coûte **22-38 ms** (`/api/agents/activity`,
3 agents vivants sur 324) : 7 fois moins cher, et la fraîcheur ne dépend plus d'aucun délai.

LE PARTAGE. L'arbre reste mémorisé — il est dominé par des subprocess git, des prompts et des
agents terminés, toutes choses qui ne bougent pas d'une seconde à l'autre. Seuls les champs
qu'un agent change plusieurs fois par tour sont relus par-dessus, et seulement pour les
agents que `activity.report()` déclare vivants : le coût suit le nombre d'agents VIVANTS,
jamais la taille du parc.

Un node absent du recensement n'est plus vivant : ses champs volatils sont RETIRÉS, jamais
laissés tels quels. Sans cette règle, un agent terminé garderait le badge « démarrage de
l'agent… » jusqu'à l'expiration du cache — une phase qui ment est pire qu'une phase en retard.
"""
from __future__ import annotations

from . import activity

# Les champs qu'un agent change PLUSIEURS FOIS pendant un tour. Tout le reste (titre, projet,
# branche, verdict, vivacité, prompt) est stable à l'échelle du TTL et reste servi du cache.
# `state` n'en fait délibérément PAS partie : il est calculé dans la même passe que `liveness`,
# `verdict`, `suspect_dead` et `interrupted`, qu'il faudrait alors recalculer avec lui sous
# peine de servir un node qui se contredit.
VOLATILE_FIELDS = ("phase", "phase_label", "phase_detail", "phase_at",
                   "activity", "activity_live", "activity_label", "last_event_at",
                   "idle_seconds", "stale", "turn")


def overlay(page: dict) -> dict:
    """La page d'arbre, avec les champs volatils de ses nodes vivants relus à l'instant.

    La page mémorisée n'est JAMAIS modifiée : les nodes qui changent sont recopiés. Muter
    l'objet du cache le corromprait pour tous les lecteurs suivants, y compris ceux qui lisent
    une autre page — `fleet_cache` partage ses entrées entre threads."""
    live = {row["key"]: row for row in activity.report()["agents"]}
    return {**page, "nodes": [_refreshed(n, live.get(n["key"])) for n in page["nodes"]]}


def _refreshed(node: dict, live_row: dict | None) -> dict:
    """Le node, avec ses champs volatils remplacés par ceux du recensement (ou retirés).

    Rendu TEL QUEL — même objet — quand rien ne diffère : le cas de très loin le plus fréquent
    (le parc est fait d'agents terminés), et celui où toute copie serait du travail pur perdu."""
    fresh = {key: live_row[key] for key in VOLATILE_FIELDS if key in (live_row or {})}
    # `phase` fait partie du contrat du node d'arbre : `fleet._node` le sert toujours, même
    # vide. Un champ qui disparaît selon la vivacité obligerait chaque lecteur à distinguer
    # « pas de phase » de « pas de champ », deux façons de dire la même chose.
    fresh.setdefault("phase", "")
    if all(node.get(key) == fresh.get(key) for key in VOLATILE_FIELDS):
        return node
    return {**{k: v for k, v in node.items() if k not in VOLATILE_FIELDS}, **fresh}
