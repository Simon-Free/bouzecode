# [desc] Index de méta des sessions : memo process devant le fichier de reprise à chaud. [/desc]
"""Sortir la méta d'une session (titre, modèle, nombre de tours, date, close_reason) oblige
à DÉCODER son JSON ENTIER. Il n'y a pas de raccourci : `saved_at`/`model`/`first_message`
sont bien en tête de fichier, mais `turn_count` et `close_reason` sont écrits APRÈS le
tableau `messages` (cf. `backend/commands/session/session.py::_build_session_data`), donc
une lecture bornée de la queue ne les trouve pas — vérifié sur 60 sessions, 60 divergences.

Ce que ça coûte, mesuré sur le poste avec index vide : 515 sessions, **772 Mo décodés,
55 s** pour UN SEUL GET /api/sessions (une session CLI atteint 112 Mo à elle seule).
L'index par mtime est donc la seule chose qui rend l'endpoint tenable, et chaque entrée
perdue se paie immédiatement en secondes.

Deux étages, consultés dans cet ordre :
  1. ``_memo`` — mémoire du PROCESS, autorité pendant sa vie.
  2. ``index_cache.json`` — reprise à chaud après un redémarrage du serveur.

Pourquoi le memo : le fichier était rechargé puis réécrit EN ENTIER à chaque appel. Le poll
``/api/agents/tree`` (toutes les 8 s) et un ``GET /api/sessions`` le chargeaient chacun de
son côté, puis la dernière écriture écrasait les entrées de l'autre. Une entrée perdue =
une session re-décodée au prochain appel, sur un corpus pourtant inchangé — c'est ainsi que
l'endpoint retombait à 27 s. Le memo rend cette perte inoffensive dans le process, et
``merge_into_file`` cesse d'écraser le fichier pour que la perte ne survive pas non plus
à un redémarrage.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

# path (str) -> (mtime, meta). Une entrée par session, jamais le contenu des messages :
# ~400 octets par session, soit ~0,3 Mo pour les 800 sessions du poste.
_memo: dict[str, tuple[float, dict]] = {}
_memo_lock = threading.Lock()


def memoized_meta(path: Path, disk_index: dict, build) -> dict:
    """Méta de `path` : memo process, puis `disk_index`, et seulement en dernier `build()`.

    `build` (injecté) est le décodage coûteux du JSON de session. Il n'est appelé que si les
    DEUX étages manquent pour le mtime courant. `disk_index` est enrichi sur place : c'est
    l'appelant qui le sauve, une seule fois pour tout son listing."""
    key = str(path)
    mtime = path.stat().st_mtime
    with _memo_lock:
        memoized = _memo.get(key)
    if memoized is not None and memoized[0] == mtime:
        return memoized[1]
    entry = disk_index.get(key)
    if isinstance(entry, dict) and entry.get("mtime") == mtime:
        meta = entry["meta"]
    else:
        meta = build()
        disk_index[key] = {"mtime": mtime, "meta": meta}
    with _memo_lock:
        _memo[key] = (mtime, meta)
    return meta


def reset_memo() -> None:
    """Vide le memo. Réservé à l'isolation des tests (le process serveur ne l'appelle pas)."""
    with _memo_lock:
        _memo.clear()


def read_file(path: Path) -> dict:
    """Index sur disque, ou {} si absent/illisible (un index perdu se reconstruit)."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_into_file(path: Path, fresh: dict) -> None:
    """Écrit `fresh` FUSIONNÉ avec ce qui est déjà sur disque, au lieu de l'écraser.

    Sans la fusion, deux requêtes concurrentes se volaient leurs entrées : la dernière à
    sauver rendait au fichier son état d'avant l'autre, et les sessions ainsi oubliées
    étaient re-décodées (des secondes) au prochain appel, même après redémarrage.

    Écriture best-effort : un tmp unique par appel (threads Flask et instances
    concurrentes), et une course perdue sur le replace Windows (WinError 32) abandonne
    juste cette sauvegarde — le fichier sera réécrit au prochain listing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**read_file(path), **fresh}
    tmp_path = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    tmp_path.write_text(json.dumps(merged), encoding="utf-8")
    try:
        tmp_path.replace(path)
    except OSError:
        tmp_path.unlink(missing_ok=True)


def sweep_orphan_tmp(path: Path, older_than_seconds: float = 3600.0) -> list[str]:
    """Supprime les `.tmp` d'écriture ABANDONNÉS à côté de `path`. Renvoie leurs noms.

    `merge_into_file` nettoie son tmp quand le `replace` échoue, mais pas quand le PROCESS
    MEURT entre les deux : un serveur tué laisse alors un fichier derrière lui pour toujours.
    Constaté sur le poste : 70 `index_cache.*.tmp` de 0 octet, datés des 4 et 15 juillet,
    jamais réclamés. Aucun n'est nuisible seul — ils encombrent, et surtout ils masquent le
    signal qu'un tmp récent, lui, porterait vraiment.

    Le plancher d'âge est la seule garde nécessaire : un tmp de moins d'une heure peut
    appartenir à une écriture EN COURS dans un autre thread ou une autre instance."""
    import time

    cutoff = time.time() - older_than_seconds
    removed = []
    for orphan in path.parent.glob(f"{path.stem}.*.tmp"):
        if orphan.stat().st_mtime > cutoff:
            continue
        orphan.unlink(missing_ok=True)
        removed.append(orphan.name)
    return removed
