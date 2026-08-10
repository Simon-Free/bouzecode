# [desc] Side-call that judges which snippets of the methodology note are spent. [/desc]
"""The deep half of note compaction: a per-snippet keep-or-drop judgement.

Why a side-call and not the agent itself: the judgement needs the WHOLE note,
which the agent's own turn would have to re-read, and it must not spend the
agent's turn nor pollute its context. The call is given the mission (the first
``## User`` block) and the most recent prose so it can tell a still-relevant
snippet from a spent one.

Why headers only, never bodies: the header carries path, range or symbol, label
and size — everything a relevance judgement needs. Sending 27 000 tokens of
frozen code to decide what to delete would cost more than it saves; the header
list costs one or two thousand.

The asymmetry that sets every default here: **a snippet dropped in error costs
one re-read; a decision or a failed attempt dropped in error costs a loop.**
So only ``## snippet:`` blocks are ever candidates. Prose — the plan, the
decisions, the "I tried X and it failed" — is passed as read-only context and
is never modified. Anything the judge does not explicitly mark DROP is kept.
"""
from __future__ import annotations

import logging
import os
import re

from .note_blocks import _split_into_blocks, path_of_key

log = logging.getLogger(__name__)

# Quality over price: the input is ~1-2k tokens of headers, so the model choice
# costs cents either way, while a wrong DROP costs a re-read or a loop.
JUDGE_MODEL = os.environ.get("BOUZECODE_COMPACT_JUDGE_MODEL", "claude-opus-4-8")

# A snippet made moments ago is, by construction, "not cited later in the note".
# Offering it up would let the pass eat the agent's freshest memory, so the most
# recent ones are held back until the note has had a chance to reference them.
RECENT_SNIPPETS_PROTECTED = 3

_MISSION_CHARS = 1500
_RECENT_PROSE_CHARS = 3000
_SEPARATORS = re.compile(r"[\\/]+")
_DROP_LINE = re.compile(r"^\s*DROP\s+(\d+)\b", re.MULTILINE)

_JUDGE_SYSTEM = (
    "You prune the working memory of a coding agent. You are given its mission, "
    "its most recent notes, and a numbered list of FILE SNIPPETS it froze into "
    "memory earlier.\n\n"
    "Drop a snippet only when the agent is provably done with that file for this "
    "mission. Keep anything that might still be consulted.\n\n"
    "The costs are not symmetric: a snippet you keep wrongly costs a few cents of "
    "cache; a snippet you drop wrongly makes the agent re-read a file it needed, "
    "or worse, redo work. When unsure, KEEP.\n\n"
    "Answer with one line per snippet you want dropped, nothing else:\n"
    "DROP <number>\n"
    "Answer with no lines at all if everything should be kept."
)


def _normalise(path: str) -> str:
    return _SEPARATORS.sub("/", path).lower().strip()


def _mission_and_prose(blocks: list[tuple[str, str | None]]) -> tuple[str, str]:
    """Return (mission, recent prose) drawn from the non-snippet blocks."""
    prose = [text for text, key in blocks if key is None and text.strip()]
    mission = next((p for p in prose if p.startswith("## User")), "")
    return mission[:_MISSION_CHARS], "\n\n".join(prose)[-_RECENT_PROSE_CHARS:]


def _candidates(blocks: list[tuple[str, str | None]], already_kept: set[str]) -> list[dict]:
    """Snippet blocks that may be offered to the judge.

    Two protections are applied before the judge sees anything:

    * a snippet whose path is named ANYWHERE later in the note stays — the agent
      came back to that file after freezing it, which is the strongest evidence
      available that the snippet is live (42-46 % of snippets, measured);
    * the newest ``RECENT_SNIPPETS_PROTECTED`` snippets stay whatever happens.
    """
    whole = "\n".join(text for text, _ in blocks)
    snippet_indexes = [
        i for i, (_, key) in enumerate(blocks)
        if key is not None and not key.startswith("stale:")
    ]
    newest = set(snippet_indexes[len(snippet_indexes) - RECENT_SNIPPETS_PROTECTED:])
    judgeable = set(snippet_indexes)
    out: list[dict] = []
    offset = 0
    for index, (text, key) in enumerate(blocks):
        offset += len(text) + 1
        if index not in judgeable or index in newest or key in already_kept:
            continue
        if _normalise(path_of_key(key)) in _normalise(whole[offset:]):
            continue
        out.append({
            "index": index,
            "key": key,
            "header": text.split("\n", 1)[0],
            "lines": text.count("\n"),
        })
    return out


def _ask(mission: str, prose: str, candidates: list[dict], config: dict) -> set[int]:
    """Run the side-call. Returns the set of candidate positions to drop."""
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
    side_config["max_tokens"] = 1024
    side_config.pop("_tool_choice", None)

    answer = ""
    for event in get_streamer()(
        model=JUDGE_MODEL,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
        tool_schemas=[],
        config=side_config,
    ):
        if isinstance(event, AssistantTurn):
            answer = event.text or ""
    return {int(m.group(1)) for m in _DROP_LINE.finditer(answer)}


def _tombstone(header: str, lines: int) -> str:
    """One line naming what was dropped and how to get it back."""
    what = header[len("## snippet: "):] if header.startswith("## snippet: ") else header
    return (
        f"## snippet-dropped: {what} — {lines} lines removed by compaction. "
        f"Re-run Snippet on this file/symbol if you need it again."
    )


def judge_and_prune(note: str, context_state, config: dict) -> tuple[str, int]:
    """Return (pruned_note, chars_removed). Never raises."""
    blocks = _split_into_blocks(note)
    already_kept: set[str] = getattr(context_state, "_compaction_kept", set())
    candidates = _candidates(blocks, already_kept)
    if not candidates:
        return note, 0

    # Same precedent as the enforcement side-calls in loop.py: a transient
    # provider error must never kill the session. Falling back to "change
    # nothing" is the safe side of the asymmetry.
    try:
        drops = _ask(*_mission_and_prose(blocks), candidates, config)
    except Exception as exc:  # noqa: BLE001
        log.warning("compaction judge side-call failed: %s", exc)
        return note, 0

    dropped_indexes = {
        c["index"]: c for n, c in enumerate(candidates, 1) if n in drops
    }
    # Idempotence: every snippet the judge SAW and did not drop is marked judged,
    # so a later compaction never re-litigates it and the note cannot be whittled
    # away one pass at a time.
    context_state._compaction_kept = already_kept | {
        c["key"] for c in candidates if c["index"] not in dropped_indexes
    }
    kept: list[str] = []
    for index, (text, _key) in enumerate(blocks):
        candidate = dropped_indexes.get(index)
        kept.append(_tombstone(candidate["header"], candidate["lines"]) if candidate else text)
    pruned = "\n".join(kept).strip() if dropped_indexes else note
    _journal(config, candidates, dropped_indexes, len(note) - len(pruned))
    return pruned, len(note) - len(pruned)


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
