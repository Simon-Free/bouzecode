# [desc] Regroupement git : un dépôt = un projet logique ; ses worktrees = ses branches. [/desc]
"""Plie les paths enregistrés en projets logiques via `git --git-common-dir`.

Tous les worktrees d'un dépôt partagent le même common-dir → même projet logique.
Purement dérivé (projects.json n'est pas modifié). repo_key est caché à vie, mais
SEULEMENT en cas de succès (le dépôt d'un path est stable, alors qu'un path pas
encore provisionné le devient) ; branch est caché avec un court TTL (il change)."""
from __future__ import annotations

import os
import subprocess
import threading
import time

_key_cache: dict[str, str] = {}
_branch_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()
_BRANCH_TTL = 300.0
# Borne haute des deux caches : une entrée par path interrogé, donc borné par le
# nombre de worktrees, mais rien ne libérait jamais sur un serveur qui tourne des
# semaines. Au-delà de la borne on évince la plus ancienne entrée insérée (les
# dicts sont ordonnés par insertion) : pas de LRU, pas de structure dédiée.
_MAX_CACHED_PATHS = 2000


def _remember(cache: dict, path: str, value) -> None:
    """Mémorise `value` pour `path` en évinçant la plus ancienne entrée au-delà
    de _MAX_CACHED_PATHS. À appeler en tenant `_lock`."""
    if path not in cache and len(cache) >= _MAX_CACHED_PATHS:
        del cache[next(iter(cache))]
    cache[path] = value


def _git(path: str, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repo_key(path: str) -> str | None:
    """Clé canonique du dépôt d'un path (= common-dir absolu normalisé), ou None
    si le path n'est pas un dépôt git."""
    with _lock:
        if path in _key_cache:
            return _key_cache[path]
    key = None
    if os.path.isdir(path):
        common = _git(path, "rev-parse", "--git-common-dir")
        if common:
            if not os.path.isabs(common):
                common = os.path.join(path, common)
            key = os.path.normcase(os.path.normpath(os.path.realpath(common)))
    if key is None:
        # ÉCHEC NON MÉMORISÉ. Un worktree interrogé avant son provisioning n'est pas
        # encore un dépôt git ; le mémoriser figerait « pas de dépôt » pour la vie du
        # process et l'UI afficherait dépôt et branche vides jusqu'au redémarrage du
        # serveur. Le prix est un `git rev-parse` par appel tant que le path n'est pas
        # un dépôt ; le SUCCÈS, lui, reste caché à vie (le dépôt d'un path est stable).
        return None
    with _lock:
        _remember(_key_cache, path, key)
    return key


def repo_name(path: str, key: str | None) -> str:
    """Nom lisible du projet logique = dossier du dépôt (parent du common-dir)."""
    if key and os.path.basename(key) == ".git":
        return os.path.basename(os.path.dirname(key))
    if key:
        return os.path.basename(key.rstrip(os.sep)) or key
    return os.path.basename(path.rstrip("/\\")) or path


def repo_root(path: str) -> str | None:
    """Dossier de travail principal du dépôt (contient le .git), ou None."""
    key = repo_key(path)
    if key and os.path.basename(key) == ".git":
        return os.path.dirname(key)
    return None


def parent_hint(key: str) -> str:
    """Dossier parent du dépôt — désambiguïse deux dépôts de même nom de dossier."""
    repo_root = key[len("path:"):] if key.startswith("path:") else os.path.dirname(key)
    return os.path.basename(os.path.dirname(repo_root.rstrip(os.sep))) or "?"


def branch_of(path: str) -> str:
    """Branche courante du worktree (caché TTL court). '' si indéterminé."""
    now = time.time()
    with _lock:
        hit = _branch_cache.get(path)
        if hit and now - hit[0] < _BRANCH_TTL:
            return hit[1]
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD") or ""
    with _lock:
        _remember(_branch_cache, path, (now, branch))
    return branch


_COUNTS = ("agents_running", "agents_awaiting", "tickets_to_review",
           "validations_ko", "tickets_total")


def group_overview(rows: list[dict], key_fn=repo_key, name_fn=repo_name) -> list[dict]:
    """Plie des lignes projet (shape de projects.overview) en projets logiques.

    Pur : key_fn/name_fn injectables pour les tests. Les paths sans dépôt git
    restent des projets autonomes (groupe d'un seul worktree)."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        key = key_fn(row["path"]) or f"path:{row['path']}"
        group = groups.get(key)
        if group is None:
            group = {
                "key": key,
                "name": name_fn(row["path"], None if key.startswith("path:") else key),
                "worktrees": [],
                **{c: 0 for c in _COUNTS},
            }
            groups[key] = group
            order.append(key)
        group["worktrees"].append(row)
        for c in _COUNTS:
            group[c] += row.get(c, 0)
    return [groups[k] for k in order]
