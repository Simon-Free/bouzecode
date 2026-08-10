# [desc] Cache TTL + single-flight de la liste des sessions, servi à GET /api/sessions. [/desc]
"""Un listing coûte 515 `stat`, 236 statuts d'agent, et un décodage de session COMPLET pour
chaque entrée d'index manquante — mesuré index vide : 772 Mo décodés, 55 s. Rien ne
sérialisait les appels : une rafale (plusieurs onglets, un agent qui interroge l'API, un
watchdog) repayait le calcul entier autant de fois qu'il y avait de requêtes, et sur un
index froid les requêtes concurrentes décodaient chacune le même corpus.

Cache TTL court + single-flight, même motif que `web_v2/version.py::cached_version_state`
et `services/work/projects.py` : une rafale ne paie qu'un seul calcul. Cache
mono-emplacement, la clé est `include_tests` (deux valeurs possibles en pratique).
"""
from __future__ import annotations

import threading
import time

from . import store

_cache: tuple | None = None  # (include_tests, listing, échéance)
_cache_lock = threading.Lock()
_compute_lock = threading.RLock()
# 5 s : la liste sert un inventaire (titres, tours, statuts), jamais un flux temps réel — le
# suivi live d'une conversation passe par /api/sessions/<key>/blocks, qui n'est pas caché.
TTL_S = 5.0


def cached_list_sessions(
    include_tests: bool = False,
    *,
    now=time.monotonic,
    ttl: float = TTL_S,
    compute=None,
) -> dict:
    """`store.list_sessions` mémorisé pendant `ttl` secondes.

    `now`/`ttl`/`compute` sont injectables : les tests pilotent l'horloge et comptent les
    recalculs sans attendre le vrai temps. `compute=None` → `store.list_sessions`, résolu à
    l'appel pour rester substituable par monkeypatch."""
    global _cache
    build = compute if compute is not None else store.list_sessions
    with _cache_lock:
        if _cache and _cache[0] == include_tests and now() < _cache[2]:
            return _cache[1]
    with _compute_lock:  # single-flight : un seul thread reconstruit le listing
        with _cache_lock:
            if _cache and _cache[0] == include_tests and now() < _cache[2]:
                return _cache[1]
        listing = build(include_tests=include_tests)
        with _cache_lock:
            _cache = (include_tests, listing, now() + ttl)
        return listing


def reset() -> None:
    """Oublie le listing mémorisé. Réservé à l'isolation des tests."""
    global _cache
    with _cache_lock:
        _cache = None
