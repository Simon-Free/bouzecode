# [desc] Defines ContextState dataclass and resolver for per-run agent context/notes state. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field


METHODOLOGY_NOTE = "methodology"


@dataclass
class ContextState:
    notes: dict = field(default_factory=dict)
    deferred_queue: list = field(default_factory=list)
    # Contexte de session figé au premier appel (cf. contexte_fige.py) : le bloc envoyé, la
    # dernière situation vue, et le journal des notes de harnais nées de ses changements (elles
    # sont empilées dans notes[METHODOLOGY_NOTE], seule copie envoyée). Sauvegardés avec la
    # session : une reprise envoie le même bloc et la même note.
    contexte_fige: str = ""
    situation_vue: dict = field(default_factory=dict)
    notes_de_contexte: list = field(default_factory=list)
    # Mémoire du projet figée au premier appel (cf. memoire_figee.py) : la section envoyée
    # (None tant que rien n'est figé — une mémoire vide se fige aussi) et la dernière vue.
    memoire_figee: str | None = None
    memoire_vue: dict = field(default_factory=dict)
    # Nombre de fois où la note a été ALLÉGÉE (compaction) : le repli collant se lève quand il
    # change (agent/repli_collant.py), le contexte qui faisait refuser le principal ayant maigri.
    allegements: int = 0
    # Tour (state.turn_count) de la dernière compaction effective : la pré-compaction avant
    # expiration du cache (compact_precache.precache_compact) exige un écart minimal.
    last_compact_turn: int = 0


def state_du_contexte(context_state: ContextState) -> dict:
    """Ce que la session sauvegarde de l'état : la note, le contexte de session et la mémoire figés."""
    return {"notes": context_state.notes,
            "contexte_fige": getattr(context_state, "contexte_fige", ""),
            "situation_vue": getattr(context_state, "situation_vue", {}),
            "notes_de_contexte": getattr(context_state, "notes_de_contexte", []),
            "notes_de_contexte_empilees": True,
            "memoire_figee": getattr(context_state, "memoire_figee", None),
            "memoire_vue": getattr(context_state, "memoire_vue", {})}


def restaurer_le_contexte(context_state: ContextState, sauve: dict) -> ContextState:
    """Recharge EN PLACE ce que `state_du_contexte` a sauvegardé (une session antérieure n'a
    que `notes` : son contexte se figera au premier appel de la reprise). Les notes de contexte
    d'une session sauvegardée avant leur empilement (elles partaient en <harness_notes>) sont
    empilées dans la note une fois, pour que le modèle ne les perde pas."""
    context_state.notes = dict(sauve.get("notes") or {})
    context_state.contexte_fige = sauve.get("contexte_fige") or ""
    context_state.situation_vue = dict(sauve.get("situation_vue") or {})
    context_state.notes_de_contexte = list(sauve.get("notes_de_contexte") or [])
    if context_state.notes_de_contexte and not sauve.get("notes_de_contexte_empilees"):
        from .contexte_fige import empiler_note_de_contexte
        anciennes, context_state.notes_de_contexte = context_state.notes_de_contexte, []
        for note in anciennes:
            empiler_note_de_contexte(context_state, note)
    context_state.memoire_figee = sauve.get("memoire_figee")
    context_state.memoire_vue = dict(sauve.get("memoire_vue") or {})
    return context_state


def resolve_context_state(config: dict) -> "ContextState | None":
    """Read the per-run state object from config under "_context_state"."""
    return config.get("_context_state")
