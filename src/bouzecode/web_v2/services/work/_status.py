"""Libellé de statut d'un ticket : PROJECTION PURE de son état persisté (aucune I/O).

Avant le lot L2, ce module DÉRIVAIT le statut de huit drapeaux et de la vivacité des agents,
en concurrence avec quatre autres dérivations (`liveness`, `workflow`, `reaper`, worktree).
Le statut est désormais le mot historique de `ticket.state` (`etat_ticket.statut`) : il ne
peut plus contredire la fiche, la liste, l'arbre ou le Bureau, qui lisent le même champ.
`tickets.derive_status` reste l'API publique (ré-export)."""
from __future__ import annotations

from .etat_ticket import statut


def derive_status(ticket: dict) -> str:
    """Le mot historique du ticket (« en cours », « à relire », « planté »…)."""
    return statut(ticket)


def remaining_of(ticket: dict, open_points: int = 0) -> dict:
    """L'ACTE RESTANT sur un ticket dont l'agent a fini : travail non intégré, points ouverts.

    `delivery` est posé sur le ticket au tick du watchdog (`unmerged.scan`), en fin de run et
    sur refresh — jamais dans un chemin de lecture (budget 300 ms p95). Seul compte le TRAVAIL :
    des commits qui ne touchent que des fichiers de méta (uv.lock, SYMBOLS.md…) ne sont pas un
    acte restant (`residu`). Un ticket d'avant L3 sans `delivery` garde son ancien compte."""
    livraison = ticket.get("delivery") if isinstance(ticket.get("delivery"), dict) else None
    if livraison is not None:
        code = int(livraison.get("code_files_ahead") or 0)
        travail = int(livraison.get("commits_ahead") or 0) if code > 0 else 0
    else:
        brut = ticket.get("unmerged_commits")
        travail = brut if isinstance(brut, int) else 0
    points = open_points if isinstance(open_points, int) else 0
    return {"unmerged_commits": max(travail, 0), "open_points": max(points, 0)}
