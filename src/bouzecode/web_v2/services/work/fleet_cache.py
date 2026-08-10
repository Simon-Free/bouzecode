# [desc] Cache « servir d'abord, recalculer ensuite » des pages d'arbre d'agents, avec un verrou par clé. [/desc]
"""Le cache de `fleet.agent_tree`, sorti de fleet.py : une seule responsabilité, testable seule.

CE QU'IL CORRIGE, mesuré sur le parc réel (251 nodes, 94 worktrees git) :
  * l'arbre coûte 2,2 s pour 15 racines et 9,45 s en entier, dominé par des subprocess git ;
  * le TTL (10 s) tombe SOUS la cadence de poll du front (8 s) → une requête sur deux payait ce
    prix EN LIGNE. C'est la lenteur rapportée de l'interface ;
  * le verrou de calcul était GLOBAL → l'arbre complet demandé par un agent de monitoring
    (9,45 s) faisait attendre derrière lui la page de l'interface, qui ne partage pourtant
    aucune entrée avec lui.

DEUX RÈGLES, et rien d'autre :
  1. si une version existe, elle est servie IMMÉDIATEMENT ; périmée, elle déclenche un
     recalcul de FOND (un seul par clé) dont le poll suivant récoltera le fruit ;
  2. le calcul est sérialisé PAR CLÉ : deux clés différentes ne s'attendent jamais.

Seul le premier appel d'une clé attend — il n'y a rien à servir.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

# Cadence de recalcul. Ce n'est plus un délai d'attente pour personne.
TTL_SECONDS = 10.0

# Au-delà de cette péremption, une entrée dont plus personne ne demande la clé est jetée. Les
# clés varient avec le scroll : sans ce ménage le cache grossirait à vie. On ne peut PAS jeter
# « tout ce qui est périmé » — le périmé récent est justement ce qu'on sert pendant un recalcul.
KEEP_AFTER_EXPIRY_SECONDS = 300.0

_entries: dict[Any, dict] = {}
_registry_lock = threading.Lock()
_compute_locks: dict[Any, threading.Lock] = {}
_refreshing: set = set()


def cached(cache_key, compute: Callable[[], Any]):
    """Valeur de `cache_key` : servie de suite si elle existe, recalculée en fond si périmée.

    `compute` est rappelé sans argument — l'appelant capture ses propres paramètres, ce module
    ne connaît donc rien de la forme des données qu'il garde."""
    with _registry_lock:
        entry = _entries.get(cache_key)
        stale = entry is not None and time.monotonic() >= entry["expires"]
        launch_refresh = stale and cache_key not in _refreshing
        if launch_refresh:
            _refreshing.add(cache_key)
    if entry is not None:
        if launch_refresh:
            threading.Thread(target=_refresh, args=(cache_key, compute), daemon=True,
                             name=f"cache-refresh{cache_key}").start()
        return entry["data"]
    return compute_and_store(cache_key, compute)


def compute_and_store(cache_key, compute: Callable[[], Any]):
    """Calcule et mémorise, un seul calcul à la fois PAR CLÉ.

    Le second arrivant sur une clé froide attend le premier puis lit son résultat, au lieu de
    refaire le même travail (dominé par des subprocess git)."""
    with _lock_for_key(cache_key):
        with _registry_lock:
            entry = _entries.get(cache_key)
            if entry and time.monotonic() < entry["expires"]:
                return entry["data"]
        data = compute()
        with _registry_lock:
            now = time.monotonic()
            _entries[cache_key] = {"data": data, "expires": now + TTL_SECONDS}
            for key in [k for k, v in _entries.items()
                        if v["expires"] + KEEP_AFTER_EXPIRY_SECONDS <= now]:
                del _entries[key]
                _compute_locks.pop(key, None)
        return data


def _lock_for_key(cache_key) -> threading.Lock:
    with _registry_lock:
        lock = _compute_locks.get(cache_key)
        if lock is None:
            lock = _compute_locks[cache_key] = threading.Lock()
        return lock


def _refresh(cache_key, compute: Callable[[], Any]) -> None:
    """Recalcul de fond. Le `finally` est OBLIGATOIRE : un recalcul qui échoue sans libérer son
    drapeau figerait la clé sur sa version périmée pour toujours — plus aucun lecteur ne
    relancerait de rafraîchissement."""
    try:
        compute_and_store(cache_key, compute)
    finally:
        with _registry_lock:
            _refreshing.discard(cache_key)


def expire_all() -> None:
    """Périme toutes les entrées SANS les jeter : le prochain lecteur sert la version connue
    et déclenche aussitôt le recalcul, au lieu d'attendre la fin du TTL.

    CE QU'ELLE CORRIGE (mesuré le 2026-08-03). Un agent qui vient de naître est sur le disque
    dès le `Popen` — `runner._save` invalide d'ailleurs déjà le cache de `list_agents`. Mais
    la PAGE d'arbre, elle, restait servie depuis ce cache-ci jusqu'à expiration : 7,9 s
    mesurées entre « l'agent existe sur disque » et « /api/agents/tree le montre ». C'était le
    poste DOMINANT du délai de démarrage ressenti — de l'attente pure, pas du travail.

    Périmer plutôt que vider est délibéré : vider ferait attendre le prochain lecteur (plus
    rien à servir), ce que tout ce module existe pour éviter."""
    with _registry_lock:
        for entry in _entries.values():
            entry["expires"] = 0.0


def clear() -> None:
    """Vide tout. Réservé à l'isolation des tests (le process serveur ne l'appelle pas)."""
    with _registry_lock:
        _entries.clear()
        _compute_locks.clear()
        _refreshing.clear()
