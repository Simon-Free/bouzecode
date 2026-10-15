# [desc] À l'adoption d'un worktree, les extraits (Snippet) gardés sous le dépôt principal sont rebasés sur le worktree quand le fichier y est identique : pas de relecture. [/desc]
"""Session 9d81964e (2026-10-06) : passé dans son worktree, l'agent a relu en 8 tours
(≈100 k tokens) les fichiers qu'il avait déjà extraits — ses extraits pointaient le dépôt
principal, plus le dossier où il travaillait. Un en-tête n'est réécrit que si le fichier est
OCTET POUR OCTET le même des deux côtés (l'arbre principal peut porter des modifications non
commitées que le worktree, sorti de HEAD, n'a pas) ; sinon l'extrait reste tel quel."""
from __future__ import annotations

import os

from .note_blocks import _SNIPPET_HEADER_RE, _STALE_MARKER_RE
from .state import METHODOLOGY_NOTE


def _normalise(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _chemin_rebase(chemin: str, racine: str, worktree: str) -> str | None:
    """Le même fichier dans le worktree, s'il est sous `racine` et identique ; sinon None."""
    absolu = _normalise(chemin)
    try:
        sous_la_racine = os.path.commonpath([absolu, _normalise(racine)]) == _normalise(racine)
    except ValueError:  # autre lecteur (Windows) : forcément hors du dépôt
        return None
    if not sous_la_racine:
        return None
    cible = os.path.join(worktree, os.path.relpath(absolu, _normalise(racine)))
    if not (os.path.isfile(absolu) and os.path.isfile(cible)):
        return None
    with open(absolu, "rb") as source, open(cible, "rb") as copie:
        return cible if source.read() == copie.read() else None


def _ligne_rebasee(ligne: str, racine: str, worktree: str) -> str | None:
    for motif in (_SNIPPET_HEADER_RE, _STALE_MARKER_RE):
        trouve = motif.match(ligne.strip())
        if trouve:
            chemin = trouve.group("path").strip()
            cible = _chemin_rebase(chemin, racine, worktree)
            return ligne.replace(chemin, cible, 1) if cible else None
    return None


def rebaser_extraits(context_state, racine: str, worktree: str) -> int:
    """Réécrit les en-têtes d'extraits `racine/…` en `worktree/…` ; rend leur nombre."""
    if context_state is None or not racine or _normalise(racine) == _normalise(worktree):
        return 0
    note = context_state.notes.get(METHODOLOGY_NOTE, "")
    lignes = note.split("\n")
    rebasees = 0
    for index, ligne in enumerate(lignes):
        if not ligne.lstrip().startswith("## snippet"):
            continue
        nouvelle = _ligne_rebasee(ligne, racine, worktree)
        if nouvelle is not None:
            lignes[index] = nouvelle
            rebasees += 1
    if rebasees:
        context_state.notes[METHODOLOGY_NOTE] = "\n".join(lignes)
    return rebasees
