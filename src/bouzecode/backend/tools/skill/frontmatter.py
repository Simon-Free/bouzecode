# [desc] Splits a skill markdown file into YAML frontmatter and body, using line-exact `---` delimiters. [/desc]
"""Frontmatter splitting for skill files.

The delimiter is a LINE that is exactly ``---`` (after strip), never a substring found
anywhere. Splitting on the substring ``---`` silently swallowed the top of the body into
the frontmatter whenever the closing delimiter was missing: the first body line holding
``---`` (a markdown table separator ``|------|``, typically) became the delimiter and
the skill loaded amputated, without a signal.

An unterminated frontmatter is an authoring error, so it raises here. Callers decide
whether that is fatal (the API refusing to save) or merely loud (the loader skipping
one bad file instead of killing startup).
"""
from __future__ import annotations

DELIMITER = "---"


class UnterminatedFrontmatterError(ValueError):
    """A skill file opens with `---` but never closes its frontmatter."""


def closing_delimiter_index(line: str) -> int:
    """Where the closing `---` starts on this line, or -1 if it does not close.

    The delimiter is a line worth exactly ``---``. One tolerated deviation: many
    generators glue it to the end of the last field with no newline in between
    (``description: "…"---``). That still keeps the delimiter INSIDE the frontmatter,
    so no body content can be swallowed — unlike a `---` found anywhere in the body.
    """
    stripped = line.strip()
    if stripped == DELIMITER:
        return 0
    head = stripped[: -len(DELIMITER)]
    if stripped.endswith(DELIMITER) and ":" in head:
        return len(head)
    return -1


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter, body) or None when the file has no frontmatter at all.

    Raises UnterminatedFrontmatterError when the opening `---` is never closed.
    """
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        return None
    for index in range(1, len(lines)):
        cut = closing_delimiter_index(lines[index])
        if cut < 0:
            continue
        last_field = lines[index].strip()[:cut]
        frontmatter = "\n".join([*lines[1:index], last_field]).strip()
        body = "\n".join(lines[index + 1:]).strip()
        return frontmatter, body
    raise UnterminatedFrontmatterError(
        "frontmatter ouvert par une ligne '---' mais jamais refermé "
        "(il faut une ligne valant exactement '---' avant le corps)"
    )


def parse_frontmatter_fields(frontmatter: str) -> dict[str, str]:
    """Flat `key: value` lines of a frontmatter block, keys lowercased."""
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()
    return fields
