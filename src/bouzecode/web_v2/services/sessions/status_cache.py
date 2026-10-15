"""Statuts TERMINAUX des agents, retenus SUR DISQUE d'un process à l'autre.

Un listing de conversations interroge plusieurs centaines d'agents déjà finis, et chacun
coûtait la relecture de sa fiche + de son état IPC (deux `open`, un `mkdir`) : ~1,2 s
mesurées sur 484 agents, à CHAQUE process neuf, pour un résultat qui ne change jamais.

Un agent fini est dans un état TERMINAL : une fois `finished_at` écrit, son statut est
figé. On le retient donc dans un petit fichier, à côté de l'index de méta, et un process
neuf n'a plus rien à relire. La clé de validité est `(agent_id, finished_at)` : un agent
respawné puis re-fini porte un NOUVEAU `finished_at`, donc l'ancienne entrée est ignorée
sans aucun syscall — jamais de statut périmé servi.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import meta_index

_lock = threading.Lock()
_disque: dict | None = None
_chemin_charge: Path | None = None
_a_persister: dict[str, dict] = {}


def chemin() -> Path:
    """Fichier des statuts terminaux, TOUJOURS à côté de l'index de méta (`store.CACHE_PATH`).

    Dérivé à chaque appel, jamais figé à l'import : les tests (et l'isolation du HOME de
    production) redirigent déjà `store.CACHE_PATH` vers leur `tmp_path`, et ce fichier les
    suit sans qu'ils aient un second chemin à connaître."""
    from . import store

    return store.CACHE_PATH.with_name("status_cache.json")


def _entrees() -> dict:
    """Contenu du fichier, lu UNE fois par process (et re-lu si le chemin a changé)."""
    global _disque, _chemin_charge
    path = chemin()
    with _lock:
        if _disque is None or _chemin_charge != path:
            _disque = meta_index.read_file(path)
            _chemin_charge = path
        return _disque


def statut_prouve(agent_id: str, finished_at: str) -> dict | None:
    """Statut « finished » déjà prouvé pour cet agent, ou None.

    None dès que le moindre doute existe (entrée absente, `finished_at` différent, statut
    non terminal) : on recalcule alors normalement."""
    entry = _entrees().get(agent_id)
    if not isinstance(entry, dict) or entry.get("finished_at") != finished_at:
        return None
    status = entry.get("status")
    if not isinstance(status, dict) or status.get("state") != "finished":
        return None
    return status


def memoriser(agent_id: str, finished_at: str, status: dict) -> None:
    """Retient un statut terminal, à écrire au prochain `flush()`.

    On n'écrit pas ici : un listing découvre des centaines d'agents finis et réécrirait le
    fichier autant de fois."""
    with _lock:
        _a_persister[agent_id] = {"finished_at": finished_at, "status": status}


def flush() -> None:
    """Écrit les statuts terminaux découverts depuis le dernier appel (no-op si aucun).

    Fusion avec le disque (`meta_index.merge_into_file`) : deux listings concurrents ne se
    volent pas leurs entrées."""
    with _lock:
        fresh = dict(_a_persister)
        _a_persister.clear()
        if fresh and _disque is not None:
            _disque.update(fresh)
    if fresh:
        meta_index.merge_into_file(chemin(), fresh)


def reset() -> None:
    """Oublie tout ce qui est en mémoire (le fichier reste) : simule un process neuf."""
    global _disque, _chemin_charge
    with _lock:
        _disque = None
        _chemin_charge = None
        _a_persister.clear()
