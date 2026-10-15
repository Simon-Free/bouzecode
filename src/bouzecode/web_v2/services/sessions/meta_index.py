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


#  Fichiers d'index déjà versés dans le memo par CE process (cf. `amorcer`).
_amorces: set[str] = set()


def clear_memo() -> None:
    """Vide le memo PROCESS (les étages index disque et build restent intacts).

    Public parce qu'un test doit pouvoir rejouer un listing « comme dans un process neuf »
    pour prouver qu'aucun session.json n'est redécodé quand l'index disque est à jour."""
    with _memo_lock:
        _memo.clear()
        _amorces.clear()


def amorcer(index_path: Path) -> None:
    """Verse l'index disque dans le memo, UNE fois par process (et par fichier).

    Le memo est ensuite l'autorité : le fichier (5,9 Mo) était relu et décodé à CHAQUE listing,
    soit à chaque recalcul de l'arbre des agents (0,1 s toutes les 10 s), alors qu'il ne peut
    rien apprendre au process qui l'a lui-même rempli."""
    cle = str(index_path)
    with _memo_lock:
        if cle in _amorces:
            return
    entrees = read_file(index_path)
    with _memo_lock:
        for chemin, entree in entrees.items():
            if isinstance(entree, dict) and "mtime" in entree and isinstance(entree.get("meta"), dict):
                _memo.setdefault(chemin, (entree["mtime"], entree["meta"]))
        _amorces.add(cle)


def memoized_meta(path: Path, fresh_index: dict, build) -> dict:
    """Méta de `path` : memo process (amorcé depuis l'index disque, cf. `amorcer`), et
    seulement en dernier `build()`.

    `build` (injecté) est le décodage coûteux du JSON de session. Il n'est appelé que si le
    memo n'a rien pour le mtime courant. Une méta bâtie est ajoutée à `fresh_index` : c'est
    l'appelant qui le fusionne dans le fichier, une seule fois pour tout son listing."""
    key = str(path)
    mtime = path.stat().st_mtime
    with _memo_lock:
        memoized = _memo.get(key)
    if memoized is not None and memoized[0] == mtime:
        return memoized[1]
    meta = build()
    fresh_index[key] = {"mtime": mtime, "meta": meta}
    with _memo_lock:
        _memo[key] = (mtime, meta)
    return meta


def reset_memo() -> None:
    """Vide le memo. Réservé à l'isolation des tests (le process serveur ne l'appelle pas)."""
    clear_memo()


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


class DirtyTrackingIndex(dict):
    """Index de méta qui SAIT s'il a été modifié. Sous-classe de `dict` : le contrat
    `cache: dict` des appelants (fleet, list_agent_sessions) est inchangé.

    Un listing de sessions déjà indexées ne change AUCUNE entrée, et pourtant on
    réécrivait tout le fichier (5,9 Mo mesurés) à chaque requête : 0,31 s de fusion +
    0,13 s d'encodage JSON pour rien."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dirty = False

    def __setitem__(self, key, value):
        if super().get(key) != value:
            self.dirty = True
        super().__setitem__(key, value)

    def __delitem__(self, key):
        self.dirty = True
        super().__delitem__(key)


def load_index(path: Path) -> DirtyTrackingIndex:
    """Index disque, en version « je sais si j'ai changé » (cf. `save_index`)."""
    return DirtyTrackingIndex(read_file(path))


def save_index(path: Path, index: dict) -> None:
    """Sauve l'index — mais seulement s'il a RÉELLEMENT changé.

    Un index inchangé (cas ordinaire : toutes les sessions listées sont déjà indexées)
    n'est ni fusionné, ni encodé, ni remplacé. Un `dict` ordinaire, lui, est toujours
    écrit : le comportement d'avant reste disponible pour un appelant qui l'attend."""
    if isinstance(index, DirtyTrackingIndex) and not index.dirty:
        return
    merge_into_file(path, index)
    if isinstance(index, DirtyTrackingIndex):
        index.dirty = False


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
