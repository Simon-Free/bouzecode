# [desc] Journal PERSISTANT de chaque arrêt d'agent décidé par le serveur (kill, éviction, cancel.flag) : qui, pourquoi, sur quelles dates, pid vérifié ou non. [/desc]
"""Journal des arrêts d'agents : une ligne JSON par geste, dans `<parc>/_arrets.jsonl`.

Le 2026-09-29, ~160 `cancel.flag` ont été écrits en une matinée (des agents morts depuis des
semaines, et des conversations vivantes évincées 15 s après leur tour) sans qu'AUCUNE trace
ne dise quel chemin les avait posés : le serveur journalise sur une console que personne ne
lit. Chaque geste qui arrête un agent passe donc ici, quel que soit l'appelant.

Emplacement : À CÔTÉ des fiches (`agent_fiche.AGENTS_DIR`), relu à chaque appel. Un parc isolé par
les tests isole donc aussi son journal, et `*.jsonl` n'est pas ramassé par le glob `*.json`
de `list_agents`. Rotation simple : au-delà de `TAILLE_MAX`, le fichier devient `.1`.

Écriture best-effort : un journal illisible ou un disque plein ne doit jamais empêcher un
arrêt demandé — l'échec est tracé dans le log du process, pas avalé.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

from bouzecode.web_v2.services.horodatage import maintenant_iso

NOM_DU_JOURNAL = "_arrets.jsonl"
TAILLE_MAX = 5 * 1024 * 1024

_verrou = threading.Lock()
_log = logging.getLogger(__name__)


def chemin_du_journal() -> Path:
    from .runner import agent_fiche  # local : `runner` importe ce module
    return Path(agent_fiche.AGENTS_DIR) / NOM_DU_JOURNAL


def _appelants(profondeur: int = 4) -> list[str]:
    """Les premiers appelants HORS de ce module et du paquet `runner` : le chemin qui a décidé."""
    trace: list[str] = []
    frame = sys._getframe(2)
    while frame is not None and len(trace) < profondeur:
        fichier = frame.f_code.co_filename.replace("\\", "/")
        if not (fichier.endswith("/kill_journal.py") or "/runtime/runner/" in fichier):
            trace.append(f"{'/'.join(fichier.split('/')[-2:])}:{frame.f_code.co_name}")
        frame = frame.f_back
    return trace


def journaliser(geste: str, agent, **details) -> dict:
    """Ajoute une ligne au journal et la rend. `geste` : kill, eviction_refusee, cancel_doux…"""
    ligne = {
        "at": maintenant_iso("auto"),
        "geste": geste,
        "agent_id": getattr(agent, "agent_id", ""),
        "parent": getattr(agent, "parent", ""),
        "ticket": f"{getattr(agent, 'ticket_slug', '')}/{getattr(agent, 'ticket_id', '')}",
        "pid": getattr(agent, "pid", None),
        "pid_create_time": getattr(agent, "pid_create_time", 0.0),
        "returncode": getattr(agent, "returncode", None),
        "serveur_pid": os.getpid(),
        "appelants": _appelants(),
        **details,
    }
    try:
        chemin = chemin_du_journal()
        with _verrou:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            if chemin.exists() and chemin.stat().st_size > TAILLE_MAX:
                os.replace(chemin, chemin.with_name(chemin.name + ".1"))
            with chemin.open("a", encoding="utf-8") as fichier:
                fichier.write(json.dumps(ligne, ensure_ascii=False, default=str) + "\n")
    except OSError:
        _log.exception("journal des arrêts : écriture impossible (%s)", ligne)
    return ligne


def lire(chemin: Path | None = None) -> list[dict]:
    """Les lignes du journal, dans l'ordre (vide s'il n'existe pas)."""
    chemin = chemin or chemin_du_journal()
    if not chemin.exists():
        return []
    return [json.loads(ligne) for ligne in chemin.read_text(encoding="utf-8").splitlines()
            if ligne.strip()]
