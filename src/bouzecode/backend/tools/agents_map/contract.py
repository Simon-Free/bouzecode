# [desc] Mechanical validation of a generated map: required sections, call-line annotation, cited symbols, Zoom ranges. [/desc]
from __future__ import annotations

import re

_CALL_LINE = re.compile(r"^[\s│]*[├└]──\s")
_ANNOTATED = re.compile(r"\[[\w./\- ]+\]\s*$|→\s*\[see [^\]]+\]\s*$")


def has_section(md: str, name: str) -> bool:
    return bool(re.search(r"^##\s+" + re.escape(name) + r"\b", md, re.MULTILINE))


def call_lines(md: str) -> list[str]:
    """Every CALL line of a tree — the two-dash connector, per the contract.

    One-dash lines (``├─ [if ...]``) are control-flow labels and carry no file.
    """
    return [ln.rstrip() for ln in md.splitlines() if _CALL_LINE.match(ln)]


def annotation_rate(md: str) -> float:
    """Share of call lines carrying a ``[file]`` annotation."""
    lines = call_lines(md)
    if not lines:
        return 1.0
    return sum(1 for ln in lines if _ANNOTATED.search(ln)) / len(lines)


def cited_identifiers(md: str) -> set[str]:
    """Identifiers a call line claims to invoke.

    Attribute calls (``path.read_text()``) and anything inside brackets are
    skipped: the owner of an attribute is not this folder's business.
    """
    out: set[str] = set()
    for line in call_lines(md):
        body = re.sub(r"\[[^\]]*\]", " ", line)
        for m in re.finditer(r"(\.)?\b([A-Za-z_]\w*)\s*\(", body):
            if not m.group(1):
                out.add(m.group(2))
    return out


def zoom_ranges(md: str) -> list[tuple[str, str, int, int]]:
    """``(function, file, start, end)`` for every ``## Zoom:`` heading."""
    pattern = re.compile(
        r"^##\s+Zoom:\s*`?(\w+)`?\(?\)?\s*[—\-]+\s*`?([\w./]+)`?\s*L(\d+)-(\d+)",
        re.MULTILINE,
    )
    return [(m[1], m[2], int(m[3]), int(m[4])) for m in pattern.finditer(md)]


def wrong_zoom_ranges(md: str, folder) -> list[str]:
    """``## Zoom`` headings whose L<a>-<b> disagrees with the real source.

    This is the check nobody ran while ``loop.py`` went from 281 to 676 lines.
    """
    from ..folder_desc.symbols import find_symbol

    wrong = []
    for fn, file_name, start, end in zoom_ranges(md):
        path = folder / file_name
        found = find_symbol(str(path), fn) if path.exists() else None
        if found is None:
            wrong.append(f"Zoom {fn}(): {file_name} has no such symbol")
        elif found != (start, end):
            wrong.append(f"Zoom {fn}(): says L{start}-{end}, really L{found[0]}-{found[1]}")
    return wrong


PURPOSE_CAP = 110
_MAX_OVER_CAP = 0.25


def purpose_cells(md: str) -> list[str]:
    """The `Purpose` cell of every folder row of a root map."""
    return [
        ln.split("|")[2].strip()
        for ln in md.splitlines()
        if ln.startswith("| [") and ln.count("|") >= 3
    ]


def over_cap_rate(md: str) -> float:
    """Share of Purpose cells longer than the contract's cap.

    A RATE, not a per-row rejection, and deliberately so: one long sentence must
    never be able to block regeneration for good, but systematic verbosity has to
    be caught. Measured before this check existed: 114 cells of 136 over the cap,
    longest 302 characters, and a root map costing 9 754 tokens to read where the
    design budgeted ~3 600 — paid once per session by every agent.
    """
    cells = purpose_cells(md)
    if not cells:
        return 0.0
    return sum(1 for c in cells if len(c) > PURPOSE_CAP) / len(cells)


def validate_root(md: str, folders: list[str]) -> list[str]:
    """Contract violations of a generated root AGENTS.md (empty list = conforms).

    The truncation check is the one that earns its keep: an answer stopped at
    ``max_tokens`` ends mid-row and silently drops every folder after it. Nothing
    in the document says so — it reads as complete, and a reader looking for a
    folder that was cut concludes it does not exist. Measured on the first real
    generation of this repository: 103 rows written for 137 code folders.
    """
    v: list[str] = []
    lines = md.splitlines()
    if not lines or not lines[0].startswith("# "):
        v.append("missing H1 title on the first line")
    if not has_section(md, "Folders"):
        v.append("missing '## Folders' section")
    last = lines[-1].rstrip() if lines else ""
    if last.startswith("|") and not last.endswith("|"):
        v.append("the document ends mid-row — the answer was cut off, not finished")
    missing = [f for f in folders if f"]({f}SYMBOLS.md)" not in md]
    if missing:
        v.append(
            f"{len(missing)} code folders have no row: {', '.join(missing[:6])}"
            + (" …" if len(missing) > 6 else "")
        )
    rate = over_cap_rate(md)
    if rate > _MAX_OVER_CAP:
        longest = max((len(c) for c in purpose_cells(md)), default=0)
        v.append(
            f"{rate:.0%} of Purpose cells exceed the {PURPOSE_CAP}-character cap "
            f"(longest {longest}); at most {_MAX_OVER_CAP:.0%} may. One sentence saying "
            "what the folder is FOR — the contents are in its own SYMBOLS.md."
        )
    return v


def validate(md: str, known_symbols: set[str] | None = None, folder=None) -> list[str]:
    """Contract violations of a generated SYMBOLS.md (empty list = conforms)."""
    v: list[str] = []
    lines = md.splitlines()
    if not lines or not lines[0].startswith("# "):
        v.append("missing H1 title on the first line")
    if not any(ln.strip() and not ln.startswith("#") for ln in lines[1:6]):
        v.append("missing one-line purpose under the H1")
    for section in ("Entry Points", "Module Reference"):
        if not has_section(md, section):
            v.append(f"missing '## {section}' section")
    if has_section(md, "Subfolders"):
        v.append("'## Subfolders' is forbidden in a SYMBOLS.md")
    if re.search(r"\]\([^)]*/SYMBOLS\.md\)", md):
        v.append("links to another folder's SYMBOLS.md (decoupling breach)")
    rate = annotation_rate(md)
    if rate < 0.9:
        v.append(f"only {rate:.0%} of call-graph lines carry a [file] annotation (need 90%)")
    if known_symbols is not None:
        unknown = sorted(cited_identifiers(md) - known_symbols)
        if unknown:
            v.append(f"call graph cites unknown identifiers: {', '.join(unknown[:8])}")
    if folder is not None:
        from .nesting import wrong_nesting

        v.extend(wrong_zoom_ranges(md, folder))
        v.extend(wrong_nesting(md, folder))
    return v
