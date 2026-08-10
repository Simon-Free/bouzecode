# [desc] Leniency layer for Snippet arguments: implicit ranges, tool_id repairs, honest refusals. [/desc]
"""Make ``Snippet`` tolerant of arguments that are *verifiably* almost right.

Measured on 2 846 sessions (`docs/investigations/tool_input_leniency.md`): in
**390 cases out of 390** where Snippet was rejected for its ``ranges``, the key
was simply ABSENT — the model named what it wanted to keep and forgot the line
numbers. The targeted content is already on the wire and its length is known,
so rejecting is pure waste.

The red line: tolerate only what can be checked without guessing.
- absent ``ranges`` -> save the WHOLE thing, whatever its size. Saving a superset
  of the intent is verifiable; it can never write something false into memory.
  A size limit used to refuse here above 60 lines, which made "keep all of it"
  impossible to express for a reference document — the exact thing an agent
  needs when its instructions point at a 1 200-line reference schema.
- a dead ``tool_id`` -> refuse. Inventing a range over some *other* result would
  put falsehoods in the working memory, which is worse than an error.

Nothing here may discard content silently, because a note the model believes
holds content it does not is the exact failure mode this whole layer exists to
avoid.
"""
from __future__ import annotations

import re

_MARKER_PREFIXES = ("file_path=", "file=")
_REPAIRABLE_ATTRS = {"discard", "label", "file_path", "symbol"}


def repair_snippet_target(params: dict) -> str:
    """Repair the two unambiguous malformations of ``tool_id``. Returns a note.

    1. ``tool_id="file_path=C:\\..."`` — the model copied the whole wire marker.
       The prefix is unambiguous: strip it and route to ``file_path``.
    2. ``tool_id='t5_b1" discard="true'`` — an XML quote break-out swallowed the
       following attributes. Cut on the first quote, re-read the tail.
    """
    tool_id = params.get("tool_id") or ""
    if not tool_id:
        return ""
    for prefix in _MARKER_PREFIXES:
        if tool_id.startswith(prefix):
            params["tool_id"] = ""
            params["file_path"] = params.get("file_path") or tool_id[len(prefix):].strip()
            return (f"NOTE: tool_id started with '{prefix}' — that marker names a FILE, "
                    f"so it was read as file_path={params['file_path']}.")
    if '"' not in tool_id:
        return ""
    head, _, tail = tool_id.partition('"')
    params["tool_id"] = head.strip()
    recovered = []
    for key, value in re.findall(r'(\w+)\s*=\s*"([^"]*)"', tail):
        if key not in _REPAIRABLE_ATTRS or params.get(key):
            continue
        params[key] = value.lower() in ("true", "1", "yes") if key == "discard" else value
        recovered.append(key)
    suffix = f" and recovered {', '.join(recovered)}" if recovered else ""
    return (f"NOTE: tool_id contained a quote — an unescaped \" in your XML ends the "
            f"attribute. Read as tool_id='{head.strip()}'{suffix}.")


def dead_tool_id_error(tool_id: str, live_ids: list[str]) -> str:
    """Refuse a tool_id that is no longer on the wire, naming what still is."""
    available = ", ".join(live_ids) if live_ids else "(none)"
    return (
        f"Error: no tool_result found for tool_id '{tool_id}'. Nothing was saved. "
        f"The ids still on the wire are: {available}. An id leaves the wire as soon "
        f"as its turn is compacted — if the result is gone, re-run the tool, or pass "
        f"file_path= if it was a file. Do NOT snippet a different id and hope: a range "
        f"resolved over the wrong result writes something false into your memory."
    )


def infer_ranges(
    file_path: str, tool_id: str, target: str, label: str, messages: list | None,
) -> tuple[list | None, str]:
    """``ranges`` was absent: measure the source that is already on the wire.

    Returns ``(ranges, message)``; ``ranges`` is None when nothing is saved and
    ``message`` is the whole tool result.
    """
    from .snippet_resolve import (
        find_tool_result_content, list_tool_result_ids, resolve_file_lines,
    )
    if tool_id:
        content = find_tool_result_content(messages, tool_id)
        if content is None:
            return None, dead_tool_id_error(tool_id, list_tool_result_ids(messages))
        line_count = len(content.split("\n"))
    else:
        lines, _resolved, error_block = resolve_file_lines(file_path)
        if lines is None:
            detail = error_block.replace("\n", " ").replace("## snippet ERROR:", "").strip()
            return None, (
                f"Error: cannot infer 'ranges' for {target} — the source could not be "
                f"read: {detail}. Nothing was saved."
            )
        line_count = len(lines)
    return decide_implicit_ranges(target, label, line_count)


def decide_implicit_ranges(
    target: str, label: str, line_count: int,
) -> tuple[list | None, str]:
    """An absent ``ranges`` means "keep all of it". Returns ``(ranges, message)``.

    ``ranges`` is None only when there is nothing at all to save; ``message`` is
    then the whole tool result.
    """
    if line_count <= 0:
        return None, (
            f"Error: {target} resolved to empty content — there is nothing to save. "
            "Nothing was written to the methodology."
        )
    return [[1, line_count]], (
        f"no 'ranges' provided → whole result saved ({line_count} lines) from {target}. "
        "If you only wanted a part of it, re-emit with ranges=[[a, b]]."
    )
