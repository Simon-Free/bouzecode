# [desc] Ce que pèse le parc d'agents web, et sa récupération EN DEUX TEMPS (rangement réversible, puis vidage daté). [/desc]
"""Inventaire et récupération d'espace du parc `~/.bouzecode/web_agents/`.

MESURÉ SUR UN POSTE RÉEL : 746 fiches d'agents, 8541 fichiers, 1,8 Go. Rien ne bornait cette
croissance, et chaque listing du parc la traverse.

CE N'EST PAS LE GROS POSTE, et il faut le dire ici pour ne pas égarer le prochain lecteur :
`~/.bouzecode` pèse 104 Go, dont 91 Go de `worktrees/` — et 81 Go de ces 91 sont les `.venv`
(166 bacs à sable, ~1 Go de dépendances chacun pour une application Python de taille
moyenne). Voir
`worktree_disk.py` : c'est là que l'espace se récupère, et sans rien détruire d'irremplaçable
puisqu'un venv se refait par `uv sync`. Ce module-ci ne traite que les artefacts de sessions.

DEUX TEMPS, JAMAIS UN SEUL. Le geste qui libère de l'espace est le seul de tout ce module qui
détruise quelque chose, et il ne porte QUE sur ce qui a déjà été rangé et attendu :

  1. `reclaim()`  — RANGE : déplace les artefacts vers `_trash/<id>/`. Rien n'est perdu,
                    `purge.restore()` ramène tout. Aucun octet libéré à ce stade.
  2. `empty_trash()` — VIDE : supprime pour de bon ce qui dort dans `_trash/` depuis assez
                    longtemps. C'est là que l'espace revient, et c'est irréversible.

Les deux sont en SIMULATION par défaut (`confirm=False`) : ils rendent ce qu'ils FERAIENT.
Un module qui détruit sur simple appel n'a pas sa place devant 1,8 Go de travail d'agents.

La vivacité n'est jamais devinée ici : `purge.est_vivant` est la seule autorité (elle croise le
process qui référence la session, le pid, puis l'état déclaré). C'est la leçon du 2026-07-28,
où un manager VIVANT a été rangé deux millisecondes après qu'un prédicat a écrit lui-même le
champ dont il tirait sa conclusion.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from bouzecode.web_v2.runtime import runner

from . import purge

# Un agent terminé depuis moins de cela reste À PORTÉE : on le relance, on lit son récap, un
# manager l'interroge encore. 14 jours = bien au-delà du cycle de vie d'un ticket observé.
DEFAULT_KEEP_DAYS = 14

# Délai de sûreté dans la corbeille avant vidage définitif. Le rangement est réversible ; ce
# délai est ce qui rend cette réversibilité UTILISABLE (encore faut-il s'apercevoir de l'erreur).
DEFAULT_TRASH_KEEP_DAYS = 7


def _artefact_bytes(agent_id: str) -> int:
    total = 0
    for artefact in purge._artefacts(agent_id):
        if artefact.is_dir():
            total += sum(f.stat().st_size for f in artefact.rglob("*") if f.is_file())
        else:
            total += artefact.stat().st_size
    return total


def _dir_bytes(root: Path) -> int:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.is_dir() else 0


def _age_days(path: Path) -> float:
    """Depuis combien de jours `path` n'a plus bougé — JAMAIS négatif.

    Le plancher à zéro n'est pas cosmétique. `st_mtime` est un flottant : converti depuis
    `st_mtime_ns`, il s'arrondit par pas d'environ 0,24 µs aux dates actuelles, et l'arrondi
    peut aller VERS LE HAUT. Un dossier écrit à l'instant se lit donc, une fois sur huit
    (mesuré : 80 tirages sur 2 000 sous Windows), avec un horodatage postérieur au
    `time.time()` relevé juste après — donc un âge négatif. `empty_trash(0)`, qui veut dire
    « vide tout ce qui est dans la corbeille », ne supprimait alors RIEN et le disait sans
    le dire, en rendant une liste vide."""
    return max(0.0, time.time() - path.stat().st_mtime) / 86400


def inventory(keep_days: float = DEFAULT_KEEP_DAYS) -> dict:
    """Ce que pèse le parc et ce qui serait rangeable, SANS RIEN TOUCHER.

    `rangeables` : agents NON VIVANTS et plus vieux que `keep_days`, du plus gros au plus
    petit — c'est l'ordre utile, quelques sessions énormes pèsent plus que des centaines de
    petites."""
    rangeables, vivants, recents = [], 0, 0
    for agent in runner.list_agents():
        if purge.est_vivant(agent):
            vivants += 1
            continue
        if purge._age_hours(agent.started_at) < keep_days * 24:
            recents += 1
            continue
        rangeables.append({
            "agent_id": agent.agent_id,
            "title": purge._agent_title(agent),
            "started_at": agent.started_at,
            "bytes": _artefact_bytes(agent.agent_id),
        })
    rangeables.sort(key=lambda row: row["bytes"], reverse=True)
    return {
        "parc_bytes": _dir_bytes(runner.AGENTS_DIR),
        "trash_bytes": _dir_bytes(purge.TRASH_DIR),
        "agents": vivants + recents + len(rangeables),
        "vivants": vivants,
        "recents": recents,
        "keep_days": keep_days,
        "rangeables": rangeables,
        "rangeable_bytes": sum(row["bytes"] for row in rangeables),
    }


def reclaim(keep_days: float = DEFAULT_KEEP_DAYS, confirm: bool = False) -> dict:
    """RANGE les agents inventoriés comme rangeables vers `_trash/<id>/`. Réversible.

    `confirm=False` (défaut) : simulation — renvoie ce qui serait rangé, sans y toucher.
    Aucun octet n'est libéré ici : c'est `empty_trash` qui rend l'espace. La vivacité est
    re-vérifiée agent par agent au moment du déplacement, pas seulement à l'inventaire : entre
    les deux, un agent a pu être relancé."""
    etat = inventory(keep_days)
    ids = [row["agent_id"] for row in etat["rangeables"]]
    if not confirm:
        return {"simulation": True, "candidats": ids,
                "bytes": etat["rangeable_bytes"], "parc_bytes": etat["parc_bytes"]}
    if not runner.destruction_permitted():
        return {"simulation": False, "ranges": [], "refuse": "destruction interdite hors exploitation"}
    ranges, refuses = [], []
    for agent_id in ids:
        agent = runner.load_agent(agent_id)
        if agent is None or purge.est_vivant(agent):
            refuses.append(agent_id)  # relancé entre-temps : on n'y touche pas
            continue
        destination = purge.TRASH_DIR / agent_id
        destination.mkdir(parents=True, exist_ok=True)
        for artefact in purge._artefacts(agent_id):
            shutil.move(str(artefact), str(destination / artefact.name))
        purge.mark_deleted(f"agent/{agent_id}", reason="parc reclaim")
        ranges.append(agent_id)
    runner._list_agents_cache.clear()
    return {"simulation": False, "ranges": ranges, "refuses": refuses}


def empty_trash(trash_keep_days: float = DEFAULT_TRASH_KEEP_DAYS,
                confirm: bool = False) -> dict:
    """VIDE définitivement la corbeille de ce qui y dort depuis plus de `trash_keep_days`.

    SEUL geste irréversible du module, et le seul qui rende de l'espace. Il ne touche QUE
    `_trash/` : un agent qui n'y a pas été rangé d'abord ne peut pas être atteint ici.
    `confirm=False` (défaut) : simulation."""
    dossiers = [d for d in purge.TRASH_DIR.iterdir()
                if d.is_dir() and _age_days(d) >= trash_keep_days] if purge.TRASH_DIR.is_dir() else []
    liberables = sum(_dir_bytes(d) for d in dossiers)
    if not confirm:
        return {"simulation": True, "dossiers": [d.name for d in dossiers],
                "bytes": liberables}
    if not runner.destruction_permitted():
        return {"simulation": False, "supprimes": [],
                "refuse": "destruction interdite hors exploitation"}
    supprimes = []
    for dossier in dossiers:
        shutil.rmtree(dossier, ignore_errors=True)
        supprimes.append(dossier.name)
    return {"simulation": False, "supprimes": supprimes, "bytes": liberables}
