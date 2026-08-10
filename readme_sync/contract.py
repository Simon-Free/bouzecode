"""README contract: the guaranteed sections every code-folder README must expose.

The contract is the source of truth for what a README must contain so that a
navigating agent can descend from the root README down to a single symbol.

`validate(md)` returns a list of violation strings (empty = the README conforms).
It only inspects the markdown text; whether a `## Subfolders` section is required
depends on the folder context (presence of code subfolders) and is enforced by the
map-propagation layer, NOT by this pure text validator.
"""

import re

# Declarative list of the sections the contract guarantees per code folder.
# Used by tests and by the map layer to know what to expect.
REQUIRED_SECTIONS = ["purpose", "Subfolders", "Module Reference"]


def purpose_of(md):
    """The one-line purpose of a README (first non-empty line under its H1)."""
    lines = md.splitlines()
    idx, _ = _first_h1(lines)
    if idx is None:
        return None
    return _purpose_after_title(lines, idx)


def _first_h1(lines):
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return i, line[2:].strip()
    return None, None


def _purpose_after_title(lines, title_idx):
    """The purpose is the first non-empty, non-heading line after the H1 title."""
    for line in lines[title_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return None
        if stripped == "---":
            return None
        return stripped
    return None


def _has_section(md, name):
    pattern = re.compile(r"^##\s+" + re.escape(name) + r"\b", re.MULTILINE)
    return bool(pattern.search(md))


def validate(md):
    """Return a list of contract violations for the given README markdown."""
    violations = []
    lines = md.splitlines()

    title_idx, title = _first_h1(lines)
    if title_idx is None:
        violations.append("missing H1 title (a line starting with '# ')")
        return violations

    purpose = _purpose_after_title(lines, title_idx)
    if not purpose:
        violations.append("missing one-line purpose right after the H1 title")

    if not _has_section(md, "Module Reference"):
        violations.append("missing '## Module Reference' section")

    return violations
