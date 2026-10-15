# [desc] Compaction de la note methodology : seuil unique de 50k tokens de préfixe caché, puis 2 side-calls LLM [/desc]
"""Compaction of the methodology note.

One trigger, one policy. When the CACHED PREFIX the provider holds for this
session crosses ``BOUZECODE_COMPACT_CACHED_TOKENS`` (50 000), two side-calls
run: one decides snippet by snippet what is still needed, the other rewrites
the note's prose as a dense briefing.

The threshold fires ONCE per climb, by design. A pass is held to a fifth of its
input, so crossing at 50 000 lands the prefix back around 10 000 — far enough
below the bar that the next turn does not re-arm it. That is what makes a level
usable as a trigger, and it is exactly what was missing: on 2026-08-22 a 425-turn
session ran 418 prose passes that kept 83 % of their input, so the prefix never
came back under the bar and the trigger stayed armed for the rest of the session.
The note reached ~79 000 tokens all the same.

The trigger fires on the cached prefix, not on the note alone, because a
removal is paid in ``cache_create``: what matters is what the re-cache will
cost, and that is exactly what the cached prefix measures.

Everything that used to gate this pass is gone on purpose: the free structural
pass (measured median yield 0.000 over 2 476 sessions), the note floor, the
spacing in turns, the "recent snippets/prose are protected" rules, the
summary-size ratios. The threshold IS the policy — below 50k nothing happens,
above it the model decides what to keep. The one survivor is not a threshold but a
termination guard: a compaction side-call must never trigger a compaction of its own
context (``est_appel_annexe``). A sub-agent is NOT a side-call: it owns a note, and
compacts it like the main agent.

The pre-expiration trigger (cache about to expire) lives in ``compact_precache``.
"""

from __future__ import annotations

import os
import threading

from .note_blocks import (  # noqa: F401  (re-exported: imported by name elsewhere)
    _extract_snippet_key, _extract_stale_key, _split_into_blocks, path_of_key,
)

# Le prefixe cache est encore MESURE (cf. `cached_prefix_tokens`, journalise a
# chaque passe) mais il ne declenche plus rien : il porte le prompt systeme, les
# schemas d'outils et l'historique, dont 52 % de volume statique sur les sessions
# du 2026-08-24/25 qu'AUCUNE passe ne peut reduire. Armer dessus faisait payer un
# appel de resume pour un gain structurellement hors d'atteinte : 238 passes sur
# 305 ont retire 0 caractere. Les deux seuils ci-dessous s'arment donc sur la
# MATIERE que la passe correspondante sait effectivement retirer.
#
# Ratio mesure sur les notes reelles (chars / tokens factures), et non un
# estimateur generique a 3,5 : la note est dense en chemins absolus, en
# identifiants et en numeros de ligne, qui se tokenisent mal. Une estimation
# trop optimiste retarde le declencheur, ce qui est exactement le defaut qu'on
# corrige.
CHARS_PER_TOKEN = 2.66

# Seuil A — la PROSE compactable. C'est la seule matiere que la passe de resume
# peut reduire, donc la seule qui a le droit de la declencher.
NOTE_PROSE_TOKENS_THRESHOLD = int(os.environ.get("BOUZECODE_COMPACT_NOTE_TOKENS", "50000"))

# Seuil B — les snippets VIVANTS. Eux ne se resument pas, ils s'elaguent : le
# juge decide lesquels ont fini de servir. Plus haut que A parce qu'un snippet
# vivant est de la matiere que l'agent a explicitement demande a garder sous les
# yeux ; on ne la lui retire pas au premier signe d'embonpoint.
LIVE_SNIPPET_TOKENS_THRESHOLD = int(os.environ.get("BOUZECODE_COMPACT_SNIPPET_TOKENS", "100000"))

# Seuil C — les extraits MORTS (perimes, temporaires, fichiers disparus, doublons). Leur
# retrait est mecanique (compact_snippets), sans appel au modele : il suffit que leur
# poids justifie de reecrire le cache une fois.
DEAD_SNIPPET_TOKENS_THRESHOLD = int(os.environ.get("BOUZECODE_COMPACT_DEAD_SNIPPET_TOKENS", "10000"))


def _tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN)


# Tout ecrivain de la note la prend sous ce verrou : la compaction avant expiration du
# cache (compact_precache) la reecrit depuis un fil minuteur pendant que la boucle, un
# outil ou un message utilisateur y ajoute.
NOTE_LOCK = threading.RLock()


def _current_turn(config: dict | None) -> int:
    state = (config or {}).get("_state")
    return int(getattr(state, "turn_count", 0) or 0)


def est_appel_annexe(config: dict) -> bool:
    """Vrai pour un appel ANNEXE (juge, resume de prose, resume de reflexion, classifieur,
    rattrapage d'enforcement, question d'image, sonde) : tous partent d'une copie de la
    config ou `_context_state` est mis explicitement a None — ils n'ont pas de note.

    `_depth` ne le dit PAS : un sous-agent de l'outil `Agent` a lui aussi `_depth >= 1`
    (agent.loop le pose), mais il tient sa propre note (`state.context_state`) et doit la
    compacter. Une config sans la cle (tests, appel direct) est une session principale.
    """
    return "_context_state" in config and config["_context_state"] is None


def _reecrire_la_note(context_state, note_key: str, lu: str, compacte: str,
                      config: dict | None) -> int:
    """Ecrit la note compactee, seulement si elle n'a fait que GRANDIR depuis la lecture
    `lu` (ajout concurrent : le suffixe ajoute est garde). Reecrite entre-temps : la passe
    est abandonnee. Renvoie les caracteres retires."""
    if compacte == lu:
        return 0
    with NOTE_LOCK:
        current = context_state.notes.get(note_key, "") or ""
        if not current.startswith(lu):
            return 0
        context_state.notes[note_key] = compacte + current[len(lu):]
        context_state.allegements = getattr(context_state, "allegements", 0) + 1
        context_state.last_compact_turn = _current_turn(config)
        if hasattr(context_state, "_methodology_cache_snapshot"):
            context_state._methodology_cache_snapshot = None
    return max(len(lu) - len(compacte), 0)


def compactable_prose_tokens(note: str) -> int:
    """Taille estimee de ce que la passe de prose pourrait effectivement retirer."""
    from .compact_prose import prose_units
    return _tokens(sum(len(u) for u in prose_units(note)))


def live_snippet_tokens(note: str) -> int:
    """Taille estimee des snippets vivants — la matiere du juge."""
    from .compact_prose import live_snippet_units
    return _tokens(sum(len(u) for u in live_snippet_units(note)))


def cached_prefix_tokens(config: dict | None) -> int:
    """Tokens the provider held in cache for the most recent LLM turn.

    ``cache_read + cache_creation`` of the last ``llm`` timing entry is the whole
    cached prefix — stable prompt, tool docs and the methodology block — which is
    exactly what a compaction forces the provider to write again. Returns 0 when
    no LLM turn has completed yet (first turn, side-calls, tests).
    """
    state = (config or {}).get("_state")
    for entry in reversed(getattr(state, "timing_entries", []) or []):
        if entry.get("phase") == "llm":
            return entry.get("cache_read_tokens", 0) + entry.get("cache_creation_tokens", 0)
    return 0


def _gates_open(context_state, note_key: str, config: dict | None, threshold: int) -> str:
    """La note a mesurer, ou "" quand aucun declencheur n'a le droit de partir.

    Gardes communes aux deux seuils : sans config il n'y a pas de session, un
    seuil <= 0 desactive le declencheur (echappatoire par variable d'env), et un
    appel annexe (``est_appel_annexe``) ne compacte jamais — le compacteur compactant
    son propre contexte recurserait sans fin. Un sous-agent, lui, passe.
    """
    if config is None or threshold <= 0:
        return ""
    if est_appel_annexe(config):
        return ""
    return context_state.notes.get(note_key, "") or ""


def should_compact(context_state, note_key: str, config: dict | None) -> bool:
    """Seuil A : la prose compactable pese-t-elle assez pour payer un resume.

    On mesure la matiere REDUCTIBLE, pas le prefixe cache. Un plafond de resume
    vaut un cinquieme de son entree : quand l'entree est mince, ce plafond
    tombe sous ce qu'un modele rend en pratique (mediane mesuree 3 979 car pour
    un plancher de reponse d'environ 5 000), et la passe est refusee d'avance.
    Attendre d'avoir vraiment de la prose a compacter, c'est s'assurer que le
    plafond est atteignable.
    """
    note = _gates_open(context_state, note_key, config, NOTE_PROSE_TOKENS_THRESHOLD)
    if not note:
        return False
    return compactable_prose_tokens(note) >= NOTE_PROSE_TOKENS_THRESHOLD


def should_prune_snippets(context_state, note_key: str, config: dict | None) -> bool:
    """Seuil B : les snippets vivants pesent-ils assez pour convoquer le juge.

    Independant de A : une note peut etre presque tout entiere en snippets
    vivants, cas ou il n'y a rien a resumer mais beaucoup a elaguer. C'est
    precisement ce que l'ancien declencheur unique ne savait pas distinguer.
    """
    note = _gates_open(context_state, note_key, config, LIVE_SNIPPET_TOKENS_THRESHOLD)
    if not note:
        return False
    return live_snippet_tokens(note) >= LIVE_SNIPPET_TOKENS_THRESHOLD


def should_clean_snippets(context_state, note_key: str, config: dict | None) -> bool:
    """Seuil C : les extraits morts pesent-ils assez pour une passe mecanique seule."""
    note = _gates_open(context_state, note_key, config, DEAD_SNIPPET_TOKENS_THRESHOLD)
    if not note:
        return False
    from .compact_snippets import poids_mort
    return _tokens(poids_mort(note)) >= DEAD_SNIPPET_TOKENS_THRESHOLD


def maybe_compact(context_state, note_key: str = "methodology", config: dict | None = None) -> int:
    """Compact the note; returns chars removed (0 when nothing was done).

    Order: the MECHANICAL snippet pass first (stale, temporary, vanished, duplicated
    snippets — no model call), then the judge on what is left, then the prose summary,
    then the safety net. Any change makes the current note stop being a prefix of the
    cached snapshot, so the snapshot is dropped and the next render pays one full
    ``cache_create`` — which is why the mechanical pass only runs at compaction time.
    """
    full_pass = should_compact(context_state, note_key, config)
    # Chemin B : rien a resumer, mais assez de snippets vivants pour convoquer
    # le juge seul. A CONTIENT B — quand les deux seuils sont franchis on ne
    # convoque le juge qu'une fois, sinon on paierait deux elagages pour un.
    prune_only = not full_pass and should_prune_snippets(context_state, note_key, config)
    if not full_pass and not prune_only and not should_clean_snippets(
            context_state, note_key, config):
        return 0

    with NOTE_LOCK:
        text = context_state.notes.get(note_key, "")
    result = _passes(text, context_state, config, judge=full_pass or prune_only,
                     summarise=full_pass)
    return _reecrire_la_note(context_state, note_key, text, result, config)


def _passes(text: str, context_state, config: dict | None, *, judge: bool,
            summarise: bool) -> str:
    from .compact_filet import elaguer_si_necessaire
    from .compact_snippets import journaliser, passe_mecanique
    mecanique = passe_mecanique(text)
    journaliser(config, text, mecanique)
    note = mecanique.note
    if judge:
        from .compact_judge import judge_and_prune
        note, _removed = judge_and_prune(note, context_state, config)
    if summarise:
        from .compact_prose import compact_prose
        note, _removed = compact_prose(note, context_state, config)
    return elaguer_si_necessaire(note, config)
