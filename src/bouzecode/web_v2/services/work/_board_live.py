# [desc] Le tri « vivant » du board : quelles tâches méritent la vue par défaut. Pur, sans Flask ni base.
"""Un board qui montre tout ne montre rien : 218 tâches dont 62 terminées ne disent plus où agir.

Ce module ne supprime RIEN — il choisit ce que la vue par défaut porte. Les tâches écartées
restent en base et restent servies par `GET /api/board?closed=1` et `GET /api/tasks?closed=1`.

Deux règles, et la deuxième est la seule subtile :
- une tâche `owner != 'agent'` est TOUJOURS gardée : son état est saisi à la main, y compris
  quand il vaut `a_faire`. C'est un plan de charge assumé, pas un reliquat de migration ;
- une tâche d'agent n'est gardée que si elle est `en_cours`, `bloquee` ou `a_relire`. Un `a_faire`
  d'agent est un ticket que personne n'a lancé, un `fait` est du travail terminé : ni l'un ni
  l'autre ne demande une décision aujourd'hui.
"""

from __future__ import annotations

LIVE_AGENT_STATES = ("en_cours", "bloquee", "a_relire")

# Recalculer `counts` ne doit pas écraser les clés qui ne sont pas des états.
NON_STATE_COUNTS = ("decisions", "closes")

# Les compteurs DÉRIVÉS d'un attribut de la tâche, et non de son `state`. Sans cette table, la
# boucle de recalcul les traitait comme des états — `sum(t.state == "arbitrages")` valant
# toujours 0 — et le board HTTP annonçait 0 arbitrage au-dessus d'une liste qui en montrait.
# La règle métier « qu'est-ce qu'un arbitrage » n'est PAS rejouée ici : on lit le drapeau
# `arbitrage` déjà posé par `build_board`, pour qu'un seul endroit en décide.
#
# `figees` et `en_cours` sont ici pour la MÊME raison : une tâche « en cours » muette depuis
# 30 min ne tourne plus (drapeau `stale` posé par `build_board`). Sans ces deux lignes, la boucle
# de recalcul remettrait `figees` à 0 (aucune tâche n'a `state == "figees"`) et recompterait
# `en_cours` en y réintégrant les figées — le board rejouerait exactement le mensonge corrigé.
DERIVED_COUNTS = {
    "arbitrages": lambda task: bool(task.get("arbitrage")),
    "a_faire_travail": lambda task: task.get("state") == "a_faire" and not task.get("arbitrage"),
    "figees": lambda task: bool(task.get("stale")),
    "en_cours": lambda task: task.get("state") == "en_cours" and not task.get("stale"),
}


def is_live(task: dict) -> bool:
    """La tâche mérite-t-elle la vue par défaut du board ?"""
    if task.get("closed_at"):
        return False
    if task.get("owner") != "agent":
        return True
    return task.get("state") in LIVE_AGENT_STATES


def keep_live(payload: dict) -> dict:
    """Le même payload de board, réduit au vivant, avec ses compteurs recalculés.

    Les compteurs sont recalculés sur la liste filtrée et non repris tels quels : annoncer
    « fait : 62 » au-dessus d'un board qui n'en montre aucune serait un mensonge de plus.
    On ne recalcule que les clés déjà présentes — la forme du payload ne change pas, ce qui
    laisse `build_board` libre d'évoluer sans casser ce filtre.
    """
    live = [task for task in payload.get("tasks") or [] if is_live(task)]
    counts = dict(payload.get("counts") or {})
    for key in counts:
        if key not in NON_STATE_COUNTS and key not in DERIVED_COUNTS:
            counts[key] = sum(1 for task in live if task.get("state") == key)
    for key, predicat in DERIVED_COUNTS.items():
        if key in counts:
            counts[key] = sum(1 for task in live if predicat(task))
    return {**payload, "tasks": live, "counts": counts}
