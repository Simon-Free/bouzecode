# [desc] Coerce Snippet-flavoured Read parameters into offset/limit, and refuse the ambiguous ones. [/desc]
"""``Read`` speaks ``offset`` (0-indexed) + ``limit``; ``Snippet`` speaks
``ranges`` (1-indexed, inclusive). The model alternates between the two tools on
the same file and mixes the vocabularies: 73 measured failures, 137 wasted turns
(`docs/investigations/tool_input_leniency.md`).

88 % of them are EXACT arithmetic conversions — no content is guessed, the very
lines asked for are the lines read — so they are converted here, with a note so
the model learns the right name instead of repeating the mistake.

Two things are never converted:
- **several ranges**: ``Read`` returns one contiguous region, so the union would
  silently hand back the in-between lines nobody asked for;
- **``command=``**: the model meant ``Bash``. Routing a Read into execution would
  bypass Bash's whole safety path. This one is a security boundary.
"""
from __future__ import annotations

import json

_VALID = ("file_path", "limit", "offset", "symbol")


def _is_line_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _as_int(value: object) -> int | None:
    """A 1-indexed line number, or None when the value is not one."""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    return value if _is_line_number(value) else None


def _as_pairs(value: object) -> list | None:
    """Parse a ``ranges``/``range`` value into a list of [start, end] pairs.

    None means "unreadable" — the caller then refuses rather than guessing.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, list) or not value:
        return None
    if all(_is_line_number(v) for v in value):  # range=[a, b], a single pair
        return [list(value)] if len(value) == 2 else None
    pairs = [v for v in value if isinstance(v, list) and len(v) == 2
             and all(_is_line_number(b) for b in v)]
    return pairs if len(pairs) == len(value) else None


def _multi_range_error(file_path: str, pairs: list) -> str:
    calls = "\n".join(
        f"  Read(file_path={file_path}, offset={a - 1}, limit={b - a + 1})    ← lines {a}-{b}"
        for a, b in pairs
    )
    union = f"[[{pairs[0][0]}, {pairs[0][1]}], ...]"
    return (
        f"Error: Read returns ONE contiguous region; you asked for {len(pairs)} ranges. "
        f"Returning their union would silently include the lines in between, which you "
        f"did not ask for and would believe absent. Emit one call per range:\n{calls}\n"
        f"(or a single Read covering the whole span, then "
        f"Snippet(ranges={union}) to keep only the pieces.)"
    )


_ORIGIN = {
    "ranges": "'ranges' belongs to Snippet",
    "range": "'range' belongs to Snippet",
    "start_line": "'start_line'/'end_line' come from another harness",
}


def _to_offset_limit(params: dict, start: int, end: int | None, source: str) -> str:
    """Apply the 1-indexed-inclusive → 0-indexed+count conversion. Returns a note."""
    params["offset"] = start - 1
    span = (f"offset={start - 1} (from line {start} to the end of the file)" if end is None
            else f"offset={start - 1}, limit={end - start + 1} (lines {start}-{end})")
    if end is not None:
        params["limit"] = end - start + 1
    return (f"[note] '{source}' is not a Read parameter — read as {span}. Read uses "
            f"offset (0-indexed) + limit; {_ORIGIN[source]} (1-indexed, inclusive).")


def normalize_read_params(params: dict) -> tuple[str | None, str]:
    """Coerce what is verifiable, refuse what is ambiguous.

    Mutates *params*. Returns ``(error, note)``: when *error* is set the call
    must NOT run; *note* is appended to the result so the model learns the name.
    """
    if "command" in params:
        return (
            "Error: 'command' is not a Read parameter — you meant Bash. Read opens a "
            "file, it executes nothing, and it will not be routed to a shell. Valid "
            f"parameters: {', '.join(_VALID)}."
        ), ""
    if "recursive" in params:
        return (
            "Error: 'recursive' is not a Read parameter — Read opens one file. To walk "
            "a tree use Glob (paths) or Grep (contents). Valid "
            f"parameters: {', '.join(_VALID)}."
        ), ""

    notes = []
    if params.pop("label", None) is not None:
        notes.append("[note] 'label' is not a Read parameter (it belongs to Snippet) — ignored.")

    key = next((k for k in ("ranges", "range") if k in params), None)
    if key is not None:
        raw = params.pop(key)
        pairs = _as_pairs(raw)
        if pairs is None:
            return (
                f"Error: '{key}' is not a Read parameter and its value {raw!r} could not "
                f"be read as line bounds either. Read uses offset (0-indexed) + limit; "
                f"'{key}' belongs to Snippet (1-indexed, inclusive)."
            ), ""
        if len(pairs) > 1:
            return _multi_range_error(params.get("file_path", "..."), pairs), ""
        if "offset" in params or "limit" in params:
            return (
                f"Error: you passed both '{key}' and offset/limit, which say different "
                f"things about where to start. Nothing was read — re-emit with offset "
                f"(0-indexed) + limit only."
            ), ""
        notes.append(_to_offset_limit(params, pairs[0][0], pairs[0][1], key))

    if "start_line" in params:
        start = _as_int(params.pop("start_line"))
        end = _as_int(params.pop("end_line", None))
        if start is None or (end is not None and end < start):
            return (
                "Error: 'start_line'/'end_line' are not Read parameters, and their values "
                "could not be read as line numbers either. Read uses offset (0-indexed) "
                "+ limit; start_line/end_line belong to other harnesses."
            ), ""
        if "offset" in params or "limit" in params:
            return (
                "Error: you passed both start_line and offset/limit, which say different "
                "things about where to start. Nothing was read — re-emit with offset "
                "(0-indexed) + limit only."
            ), ""
        notes.append(_to_offset_limit(params, start, end, "start_line"))
    params.pop("end_line", None)

    return None, "\n".join(notes)
