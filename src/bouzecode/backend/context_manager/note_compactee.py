# [desc] Note compactée sur refus content_filter : garde les ## User, les snippets et les deux derniers tours ### Tn, retire les ### Tn plus anciens ; devient l'état de la note. [/desc]
"""Compaction de la note Methodology sur refus `content_filter`, sans appel au modèle.

Ablation sur payload réel (session 28738fd0, 2026-10-12, gateway préprod) : le refus est
déterministe pour un contexte donné (10/10 à 12/12 aux tours 11 et 12) et il vient de la
note accumulée. Garder les blocs `## User`, les snippets et les deux derniers tours `### Tn`,
retirer les `### Tn` plus anciens : tour 11 de 12/12 à 0/10 (sonnet-5-5 et opus-5), tour 12
de 12/12 à 6/10. Les autres blocs `## ` (Plan, FinalAnswer, Harnais, Enfant lancé…) restaient
dans la variante mesurée : ils sont gardés aussi.

La note compactée devient l'ÉTAT de la note, pas une vue de l'appel : la note ne fait que
grossir et le refus est cumulatif, une vue temporaire ferait refuser le tour suivant à
l'identique (tours 11 puis 12). Rien n'est perdu : `notes_timeline` garde les blocs retirés
dans les deltas des tours précédents, et ce retrait y est journalisé tout de suite.
"""
from __future__ import annotations

from .methodology import _APPEND_LOCK, _TURN_STAMP_RE, _record_timeline, _split_top_level_blocks
from .state import METHODOLOGY_NOTE, resolve_context_state

TOURS_GARDES = 2


def _tour_du_bloc(bloc: str) -> int | None:
    """Le n° du tampon `### Tn` qui ouvre le bloc, None pour tout autre bloc."""
    tampon = _TURN_STAMP_RE.match(bloc.split("\n", 1)[0])
    return int(tampon.group(1)) if tampon else None


def note_compactee(note: str) -> tuple[str, list[int]]:
    """(note compactée, tours retirés). Les blocs des TOURS_GARDES derniers tours sont
    gardés — un tour peut porter plusieurs blocs `### Tn` (plusieurs appels Methodology) —,
    les blocs des tours plus anciens retirés, tout le reste gardé dans l'ordre."""
    blocs = _split_top_level_blocks(note)
    tours = sorted({t for t in map(_tour_du_bloc, blocs) if t is not None})
    retires = tours[:-TOURS_GARDES]
    if not retires:
        return note, []
    gardes = [b for b in blocs if _tour_du_bloc(b) not in retires]
    return "\n\n".join(gardes), retires


def compacter_la_note_sur_refus(config: dict) -> dict:
    """Compacte la note de la session EN PLACE et journalise le retrait dans la timeline.

    Rend {"chars_retires", "tours_retires"}, vide quand il n'y avait rien à retirer (alors
    rien n'a changé : un rejeu serait le même payload, donc le même refus)."""
    context_state = resolve_context_state(config)
    if context_state is None:
        return {}
    with _APPEND_LOCK:
        ancienne = context_state.notes.get(METHODOLOGY_NOTE, "") or ""
        nouvelle, tours_retires = note_compactee(ancienne)
        if not tours_retires:
            return {}
        context_state.notes[METHODOLOGY_NOTE] = nouvelle
        context_state._methodology_cache_snapshot = None
        context_state.allegements = getattr(context_state, "allegements", 0) + 1
    _record_timeline(config, context_state)
    return {"chars_retires": len(ancienne) - len(nouvelle), "tours_retires": tours_retires}
