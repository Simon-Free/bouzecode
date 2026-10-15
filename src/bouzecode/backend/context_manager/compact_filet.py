# [desc] Filet de sécurité : élagage mécanique de la vieille prose quand la compaction a échoué [/desc]
"""Le filet de sécurité de la compaction.

Constaté le 2026-09-24 : la synthèse de prose échouait à chaque tour (appel au mauvais
fournisseur, 401) et rien ne bornait la note, qui a atteint 375 000 caractères relus
à chaque tour. Quelle que soit la raison d'un échec — clé, réseau, réponse refusée —
la note ne doit pas pouvoir grossir sans limite.

Règle : si, APRÈS les passes de compaction, la prose compactable dépasse encore
``FACTEUR`` × le seuil, on retire mécaniquement les plus anciennes entrées de prose
jusqu'à revenir au seuil. Jamais la mission (``## User``), les notes de contexte du harnais
(``## Harnais @…``), la todolist courante, la
synthèse existante, les ``DERNIERES`` entrées ni les extraits vivants. Une ligne de
trace dit ce qui a été retiré, et le journal de session aussi.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

FACTEUR = 2
DERNIERES = 8


def _proteges(units: list[str]) -> set[int]:
    from .compact_prose import SUMMARY_HEADER, _is_harness_context, _is_mission, _is_prose
    garde = {i for i, u in enumerate(units)
             if not _is_prose(u) or _is_mission(u) or _is_harness_context(u)
             or u.lstrip().startswith(SUMMARY_HEADER)}
    todolists = [i for i, u in enumerate(units) if u.lstrip().startswith("## Todolist")]
    garde.update(todolists[-1:])
    prose = [i for i, u in enumerate(units) if i not in garde and u.strip()]
    garde.update(prose[-DERNIERES:])
    return garde


def _depasse(note: str) -> int:
    """Caractères de prose à retirer pour revenir au seuil, ou 0 si la note est dans les clous."""
    from .compact_methodology import (
        CHARS_PER_TOKEN, NOTE_PROSE_TOKENS_THRESHOLD, compactable_prose_tokens,
    )
    if NOTE_PROSE_TOKENS_THRESHOLD <= 0:
        return 0
    prose = compactable_prose_tokens(note)
    if prose < FACTEUR * NOTE_PROSE_TOKENS_THRESHOLD:
        return 0
    return int((prose - NOTE_PROSE_TOKENS_THRESHOLD) * CHARS_PER_TOKEN)


def _plus_anciens(units: list[str], garde: set[int], a_retirer: int) -> set[int]:
    retires: set[int] = set()
    for i, u in enumerate(units):
        if a_retirer <= 0:
            break
        if i not in garde and u.strip():
            retires.add(i)
            a_retirer -= len(u)
    return retires


def elaguer_si_necessaire(note: str, config: dict | None) -> str:
    """La note, élaguée de sa plus vieille prose si elle dépasse encore FACTEUR × le seuil."""
    a_retirer = _depasse(note)
    if not a_retirer:
        return note
    from .compact_prose import _units
    units = _units(note)
    retires = _plus_anciens(units, _proteges(units), a_retirer)
    if not retires:
        return note
    chars = sum(len(units[i]) for i in retires)
    trace = (f"## élagage de secours : {len(retires)} entrées anciennes retirées "
             f"({chars} caractères) — la compaction a échoué ; relis le dépôt si besoin")
    premier = min(retires)
    gardes = [trace if i == premier else u
              for i, u in enumerate(units) if i == premier or i not in retires]
    _log.warning("compaction en échec : élagage de secours de %d entrées (%d caractères)",
                 len(retires), chars)
    _journal(config, len(retires), chars)
    return "\n".join(gardes)


def _journal(config: dict | None, entrees: int, chars: int) -> None:
    log_list = getattr((config or {}).get("_state"), "compaction_log", None)
    if log_list is not None:
        log_list.append({"phase": "note_emergency_prune",
                         "turn": getattr((config or {}).get("_state"), "turn_count", 0),
                         "chars_removed": chars, "entries_removed": entrees})
