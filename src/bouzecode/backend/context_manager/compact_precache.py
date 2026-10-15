# [desc] Compaction de la note AVANT expiration du cache de prompt : minuteur armé à la fin de chaque appel au modèle, annulé au départ du suivant (lot d'outils long, pause de l'utilisateur, sous-agents compris). [/desc]
"""Compaction PRE-EXPIRATION du cache.

Le cache du gateway (litellm→Bedrock) vit 5 minutes à compter du DERNIER appel au modèle.
Passé ce délai, le prochain appel paiera de toute façon un ``cache_create`` complet :
c'est le moment gratuit pour compacter la note, puisque la réécriture du cache qu'elle
provoque aurait lieu de toute manière.

Un minuteur est armé à la fin de chaque appel au modèle (``armer_apres_appel``) et
annulé au départ du suivant (``desarmer_minuteur``). Il couvre donc d'un seul geste
tout ce qui sépare deux appels : un lot d'outils long, une question posée à
l'utilisateur, et l'attente du message suivant (REPL, TUI, agent chaud web_v2). Au bout
de ``precache_compact_delay_s`` (270 s par défaut), la passe complète tourne si la note
ENTIÈRE dépasse ``precache_compact_tokens`` et qu'aucune compaction n'a eu lieu depuis
``precache_compact_min_turns`` tours. Même pipeline que la compaction habituelle
(``_passes`` : mécanique, juge, résumé de prose, filet).
"""
from __future__ import annotations

import logging
import os
import threading

from .compact_methodology import (
    NOTE_LOCK, _current_turn, _gates_open, _passes, _reecrire_la_note, _tokens,
    est_appel_annexe,
)

PRECACHE_COMPACT_DELAY_S = float(os.environ.get("BOUZECODE_PRECACHE_COMPACT_DELAY_S", "270"))
PRECACHE_COMPACT_TOKENS = int(os.environ.get("BOUZECODE_PRECACHE_COMPACT_TOKENS", "30000"))
PRECACHE_COMPACT_MIN_TURNS = int(os.environ.get("BOUZECODE_PRECACHE_COMPACT_MIN_TURNS", "10"))


def should_precache_compact(context_state, note_key: str = "methodology",
                            config: dict | None = None) -> bool:
    threshold = int((config or {}).get("precache_compact_tokens", PRECACHE_COMPACT_TOKENS))
    text = _gates_open(context_state, note_key, config, threshold)
    if not text or _tokens(len(text)) < threshold:
        return False
    min_turns = int((config or {}).get("precache_compact_min_turns", PRECACHE_COMPACT_MIN_TURNS))
    last = int(getattr(context_state, "last_compact_turn", 0) or 0)
    return _current_turn(config) - last >= min_turns


def precache_compact(context_state, note_key: str = "methodology",
                     config: dict | None = None, passes=None) -> int:
    """Full compaction pass (judge + summary) run from the watchdog thread.

    The note is read under ``NOTE_LOCK``, the side-calls run OUTSIDE the lock (they
    take time: a user message arriving meanwhile is appended without waiting), then
    the result is written back only if the note merely GREW in the meantime: the
    appended suffix is kept. If the note was rewritten, the pass is dropped.
    Returns chars removed.
    """
    if not should_precache_compact(context_state, note_key, config):
        return 0
    with NOTE_LOCK:
        text = context_state.notes.get(note_key, "") or ""
    run = passes or (lambda t: _passes(t, context_state, config, judge=True, summarise=True))
    result = run(text)
    if not result:
        return 0
    return _reecrire_la_note(context_state, note_key, text, result, config)


def start_precache_watchdog(config: dict | None, context_state=None,
                            note_key: str = "methodology", passes=None):
    """Arm a daemon timer that runs ``precache_compact`` after ``precache_compact_delay_s``
    (default 270 s). Returns the timer (to ``cancel()``) or None when disabled: no
    session, delay <= 0, or a side-call (``est_appel_annexe``) — never a sub-agent."""
    if config is None or est_appel_annexe(config):
        return None
    delay = float(config.get("precache_compact_delay_s", PRECACHE_COMPACT_DELAY_S))
    if delay <= 0:
        return None

    def _fire():
        try:
            cs = context_state
            if cs is None:
                from .state import resolve_context_state
                cs = resolve_context_state(config)
            if cs is not None:
                precache_compact(cs, note_key, config, passes=passes)
        except Exception:  # un fil minuteur ne tue jamais la session : on journalise
            logging.getLogger(__name__).exception("precache compaction failed")

    timer = threading.Timer(delay, _fire)
    timer.daemon = True
    timer.start()
    return timer


def armer_apres_appel(config: dict, passes=None) -> None:
    """Fin d'un appel au modèle : le cache expire dans 5 min, le minuteur de la session
    (posé sur ``config["_state"]``) repart de zéro. ``passes`` : injection des tests."""
    state = config.get("_state")
    if state is None:
        return
    desarmer_minuteur(state)
    state._minuteur_precache = start_precache_watchdog(config, passes=passes)


def desarmer_minuteur(state) -> None:
    """Un appel au modèle part (le cache est relu, il ne va pas expirer), ou un sous-agent
    a fini son run (personne ne l'attend). Une passe DÉJÀ partie n'est pas interrompue :
    elle finit hors verrou et n'écrit que si la note a seulement grandi."""
    timer = getattr(state, "_minuteur_precache", None)
    if timer is not None:
        timer.cancel()
        state._minuteur_precache = None
