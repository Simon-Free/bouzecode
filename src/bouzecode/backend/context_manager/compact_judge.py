# [desc] Side-call LLM qui juge chaque snippet de la note keep-or-drop (headers seuls) et pose un tombstone [/desc]
"""The snippet half of note compaction: a per-snippet keep-or-drop judgement.

Why a side-call and not the agent itself: the judgement needs the WHOLE note,
which the agent's own turn would have to re-read, and it must not spend the
agent's turn nor pollute its context. The call is given the mission (the first
``## User`` block) and the most recent prose so it can tell a still-relevant
snippet from a spent one.

Why headers only, never bodies: the header carries path, range or symbol, label
and size — everything a relevance judgement needs. Sending 27 000 tokens of
frozen code to decide what to delete would cost more than it saves; the header
list costs one or two thousand.

Every snippet in the note is offered to the model, with no pre-filtering: the
decision is the model's, which is the whole point of paying for the call. Only
``## snippet:`` blocks are candidates — prose is passed as read-only context
here and handled by ``compact_prose``. Anything the model does not explicitly
mark DROP is kept.
"""
from __future__ import annotations

import logging
import re

from .note_blocks import _split_into_blocks, path_of_key

log = logging.getLogger(__name__)

# Quality over price: the input is ~1-2k tokens of headers, so the model choice
# costs cents either way, while a wrong DROP costs a re-read or a loop. The model is
# resolved AT CALL TIME on the session's provider (providers/side_model.py): a model
# frozen at import ignored the user's config and hit Anthropic from OpenRouter sessions.


def judge_model(config: dict | None) -> str:
    from ..agent.providers.side_model import modele_annexe
    return modele_annexe(config)

_MISSION_CHARS = 1500
_RECENT_PROSE_CHARS = 3000
_DROP_LINE = re.compile(r"^\s*DROP\s+(\d+)\b", re.MULTILINE)

_JUDGE_SYSTEM = (
    "You prune the working memory of a coding agent. You are given its mission, "
    "its most recent notes, and a numbered list of FILE SNIPPETS it froze into "
    "memory earlier.\n\n"
    "Drop a snippet when the agent is done with that file. Keep anything that "
    "might still be consulted for what it is doing NOW.\n\n"
    "If the notes show the session has MOVED ON to a different task, everything "
    "that belonged to the finished one is exactly what you should drop: those "
    "files will not be opened again.\n\n"
    "The costs are not symmetric, and not the way you might assume. A snippet you\n"
    "keep sits in a note that is rewritten into the cache on every later pass, so\n"
    "keeping it wrongly is paid again and again — measured at roughly thirty times\n"
    "the cost of dropping it wrongly, which only makes the agent re-read one file.\n"
    "So when the agent has moved away from a file, DROP. Reserve KEEP for what it is\n"
    "working on right now.\n\n"
    "Answer with one line per snippet you want dropped, nothing else:\n"
    "DROP <number>\n"
    "If nothing should be dropped, answer exactly this single line:\n"
    "KEEP ALL"
)

# Budget de SORTIE du juge. Un modele qui raisonne (DeepSeek v4.1 Flash) consommait les
# 1 024 tokens d'un budget fixe a reflechir, avant d'ecrire la moindre ligne DROP : sa
# reponse arrivait vide, coupee (stop_reason=length), et etait prise pour « tout garder »
# (rejeu du 2026-09-24 : 0 extrait retire sur 50). Plancher genereux, plus une part par
# candidat, borne par le budget de la session.
_MIN_JUDGE_TOKENS = 8192
_TOKENS_PER_CANDIDATE = 64
_KEEP_ALL = re.compile(r"^\s*KEEP\s+ALL\s*$", re.MULTILINE | re.IGNORECASE)
_TRUNCATED = {"max_tokens", "length"}


def _judge_budget(n_candidates: int, config: dict) -> int:
    from ..core.config import DEFAULTS
    cap = int(config.get("max_tokens") or DEFAULTS["max_tokens"])
    return max(min(_MIN_JUDGE_TOKENS, cap), min(cap, _MIN_JUDGE_TOKENS
                                                 + n_candidates * _TOKENS_PER_CANDIDATE))


def _verdict(answer: str, stop_reason: str | None) -> tuple[set[int], str]:
    """(positions a retirer, statut) — statut « ok », « garder » ou « invalide ».

    Une reponse vide, coupee ou sans ligne reconnue n'est JAMAIS un verdict : le modele
    doit dire explicitement KEEP ALL pour tout garder."""
    drops = {int(m.group(1)) for m in _DROP_LINE.finditer(answer)}
    if stop_reason in _TRUNCATED and not drops:
        return set(), "invalide"
    if drops:
        return drops, "ok"
    return set(), "garder" if _KEEP_ALL.search(answer) else "invalide"


def _mission_and_prose(blocks: list[tuple[str, str | None]]) -> tuple[str, str]:
    """Return (mission, recent prose) drawn from the non-snippet blocks."""
    prose = [text for text, key in blocks if key is None and text.strip()]
    mission = next((p for p in prose if p.startswith("## User")), "")
    return mission[:_MISSION_CHARS], "\n\n".join(prose)[-_RECENT_PROSE_CHARS:]


def _candidates(blocks: list[tuple[str, str | None]]) -> list[dict]:
    """Every snippet block of the note, in order — the model judges them all."""
    out: list[dict] = []
    for index, (text, key) in enumerate(blocks):
        if key is None or key.startswith("stale:"):
            continue
        out.append({
            "index": index,
            "key": key,
            "header": text.split("\n", 1)[0],
            "lines": text.count("\n"),
        })
    return out


def _ask(mission: str, prose: str, candidates: list[dict], config: dict
         ) -> tuple[set[int], str]:
    """Run the side-call. Returns (candidate positions to drop, status) — see ``_verdict``."""
    from ..agent.providers import AssistantTurn
    from ..agent.stream_interceptor import get_streamer

    listing = "\n".join(
        f"{n}. {c['header']}  ({c['lines']} lines)" for n, c in enumerate(candidates, 1)
    )
    user = (
        f"MISSION\n{mission or '(not recorded)'}\n\n"
        f"MOST RECENT NOTES\n{prose}\n\n"
        f"SNIPPETS IN MEMORY\n{listing}"
    )
    side_config = dict(config)
    side_config["_depth"] = config.get("_depth", 0) + 1
    side_config["_context_state"] = None
    side_config["max_tokens"] = _judge_budget(len(candidates), config)
    side_config.pop("_tool_choice", None)

    answer, stop_reason = "", None
    for event in get_streamer()(
        model=judge_model(config),
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
        tool_schemas=[],
        config=side_config,
    ):
        if isinstance(event, AssistantTurn):
            answer, stop_reason = event.text or "", getattr(event, "stop_reason", None)
    return _verdict(answer, stop_reason)


def _tombstone(header: str, lines: int) -> str:
    """One line naming what was dropped and how to get it back."""
    what = header[len("## snippet: "):] if header.startswith("## snippet: ") else header
    # Kept to a single short line: the tombstone must always be cheaper than the
    # block it replaces, otherwise pruning would grow the note.
    return f"## snippet-dropped: {what} ({lines} lines) — re-Snippet if needed."


def _verdict_would_repeat(context_state, candidates: list[dict]) -> bool:
    """Le meme jeu de snippets, deja juge et rien supprime : la reponse sera la meme.

    Le declencheur est un NIVEAU (prefixe cache au-dessus de 50k), pas un evenement :
    une fois la note grosse, il est franchi a chaque tour et la passe repart
    indefiniment. Mesure du 2026-08-22 sur une session de 425 tours : 431 passes pour
    89 suppressions utiles, soit 342 appels au modele pour un verdict deja rendu.
    """
    empreinte = tuple(sorted(c["key"] for c in candidates))
    return getattr(context_state, "_judge_last_noop", None) == empreinte


def judge_and_prune(note: str, context_state, config: dict) -> tuple[str, int]:
    """Return (pruned_note, chars_removed). Never raises."""
    blocks = _split_into_blocks(note)
    candidates = _candidates(blocks)
    if not candidates:
        return note, 0
    if _verdict_would_repeat(context_state, candidates):
        return note, 0

    # Same precedent as the enforcement side-calls in loop.py: a transient
    # provider error must never kill the session. Falling back to "change
    # nothing" is the safe side of the asymmetry.
    try:
        drops, statut = _ask(*_mission_and_prose(blocks), candidates, config)
    except Exception as exc:  # noqa: BLE001
        from ..agent.providers.side_model import signaler_echec
        signaler_echec("juge de compaction", judge_model(config), exc)
        return note, 0
    if statut == "invalide":
        # Pas de memo « deja juge » : la question sera reposee a la prochaine compaction.
        _signaler_reponse_invalide(context_state, judge_model(config))
        return note, 0

    return _appliquer(note, blocks, candidates, drops, context_state, config)


def _appliquer(note: str, blocks: list, candidates: list[dict], drops: set[int],
               context_state, config: dict) -> tuple[str, int]:
    """Pose les pierres tombales du verdict ; memorise un verdict sterile."""
    dropped_indexes = {
        c["index"]: c for n, c in enumerate(candidates, 1) if n in drops
    }
    kept: list[str] = []
    for index, (text, _key) in enumerate(blocks):
        candidate = dropped_indexes.get(index)
        kept.append(_tombstone(candidate["header"], candidate["lines"]) if candidate else text)
    pruned = "\n".join(kept).strip() if dropped_indexes else note
    removed = len(note) - len(pruned)
    if removed <= 0:
        # Nothing was gained: replacing tiny blocks by tombstones can cost more
        # than it saves. Growing the note would break the cache for nothing.
        # Remember the exact set judged, so the next turns do not re-ask the same
        # question: the answer cannot change while the set does not.
        setattr(context_state, "_judge_last_noop",
                tuple(sorted(c["key"] for c in candidates)))
        _journal(config, candidates, {}, 0)
        return note, 0
    # A productive verdict changes the set, so any memo is stale.
    setattr(context_state, "_judge_last_noop", None)

    _journal(config, candidates, dropped_indexes, removed)
    return pruned, removed


def _signaler_reponse_invalide(context_state, model: str) -> None:
    """Une seule alerte par session : la reponse du juge etait vide, coupee ou illisible."""
    if getattr(context_state, "_judge_invalid_reported", False):
        return
    setattr(context_state, "_judge_invalid_reported", True)
    log.warning("juge de compaction (%s) : reponse vide, coupee ou illisible — aucun extrait "
                "retire, nouvel essai a la prochaine compaction", model)


def _journal(config: dict, candidates: list[dict], dropped: dict, chars: int) -> None:
    """Record the verdict in the session so the pass can be audited afterwards.

    The candidate set splits into dropped and kept under IDENTICAL selection
    rules, so the kept half is a ready-made control group: comparing how often a
    dropped path is re-read against how often a kept one is, in the turns that
    follow, is the verification signal for "was this too aggressive?".
    """
    log_list = getattr(config.get("_state"), "compaction_log", None)
    if log_list is None:
        return
    log_list.append({
        "phase": "note_deep_compaction",
        "turn": getattr(config.get("_state"), "turn_count", 0),
        "chars_removed": chars,
        "dropped": [path_of_key(c["key"]) for c in dropped.values()],
        "kept": [path_of_key(c["key"]) for c in candidates if c["index"] not in dropped],
    })
