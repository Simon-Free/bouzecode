# [desc] Les deux mémoires de `unmerged` : refs d'un dépôt lues une fois par passe du watchdog, et comptes (commits, fichiers de code) d'un couple (base, tip) immuable. Aucun git ici. [/desc]
"""Mémoires du comptage des commits non intégrés (`unmerged`).

Relevé sous Windows (session e8bc19d3) : ~38 s de git cumulés pour 33 `scan_ticket`, soit
deux process git par ticket (tip de la branche, rev de la base) plus le rev-list — un
process git coûte 0,3 à 1 s sur ce poste. Deux mémoires :
 * PENDANT UNE PASSE (`une_passe()`, un tick) : toutes les refs d'un dépôt sont lues en UN
   `git for-each-ref`, puis chaque ticket y lit son tip et sa base. Hors passe, rien ne
   change (deux rev-parse, comme avant) : un appelant isolé voit toujours l'état courant.
 * Le COMPTE de commits d'un couple (sha de base, sha du tip) est immuable (le graphe des
   commits ne change pas) : mémorisé pour la vie du process.

Ce module ne lance aucun process : la lecture git reste dans `unmerged` (point d'accroche
des tests), qui passe ses lecteurs en argument.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable

_passe = threading.local()
_COMPTES_MAX = 4096
_comptes: dict[tuple[str, str, str], int] = {}
_codes: dict[tuple[str, str, str], int] = {}
_comptes_lock = threading.Lock()


@contextmanager
def une_passe():
    """Le temps du bloc, les refs de chaque dépôt ne sont lues qu'une fois (imbrication sûre)."""
    if getattr(_passe, "refs", None) is not None:
        yield
        return
    _passe.refs = {}
    try:
        yield
    finally:
        _passe.refs = None


def refs_de_la_passe(repo_root: str,
                     lire: Callable[[str], dict[str, str] | None]) -> dict[str, str] | None:
    """Refs du dépôt lues une fois (par `lire`) pour la passe en cours ; None hors passe."""
    memo = getattr(_passe, "refs", None)
    if memo is None:
        return None
    if repo_root not in memo:
        memo[repo_root] = lire(repo_root)
    return memo[repo_root]


def dans_les_refs(refs: dict[str, str], ref: str) -> str | None:
    """SHA de `ref` selon l'ordre de résolution de git (refs/<ref>, tags, branches, remotes) ;
    None si `ref` n'est pas un nom de ref connu (SHA, HEAD…) : l'appelant demande alors à git."""
    for nom in (ref, f"refs/{ref}", f"refs/tags/{ref}", f"refs/heads/{ref}",
                f"refs/remotes/{ref}", f"refs/remotes/{ref}/HEAD"):
        if nom.startswith("refs/") and nom in refs:
            return refs[nom]
    return None


def memorise(cache: dict[tuple[str, str, str], int], cle: tuple[str, str, str],
             calculer: Callable[[], int]) -> int:
    """Valeur de `cle` dans `cache` (`_comptes` ou `_codes`), calculée hors verrou au premier
    besoin. Le cache est vidé quand il atteint `_COMPTES_MAX` entrées."""
    with _comptes_lock:
        if cle in cache:
            return cache[cle]
    valeur = calculer()
    with _comptes_lock:
        if len(cache) >= _COMPTES_MAX:
            cache.clear()
        cache[cle] = valeur
    return valeur
