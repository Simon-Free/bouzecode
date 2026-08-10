# [desc] Edit matching helpers: uniform re-indentation repair, line-level diff of the closest block, post-edit context. [/desc]
"""Why an ``Edit`` misses, told in a way the model can act on.

Measured on 2 846 sessions (`docs/investigations/tool_input_leniency.md`),
``old_string not found`` costs **4.6 turns per failure** — 2.5x every other tool
error. The causes are NOT whitespace folklore: zero trailing-space cases, zero
Unicode look-alikes, zero CRLF (already normalised in ``_edit``). They are:

- 48 % one line differs *in content* — the model's context is one line stale;
- 18 % indentation only, uniformly shifted;
- 34 % two or more lines differ.

So the lever is the MESSAGE, not repair. ``describe_missing_old_string`` renders
a line-level diff that marks the offending lines with ``!=`` instead of dumping
20 numbered lines and letting the model hunt.

The single repair implemented, ``find_uniform_reindent``, is deliberately
narrow: the 48 % one-line-differs cases must NEVER be auto-repaired — applying
the edit on the file's line would silently delete text the model never saw.
"""
from __future__ import annotations

import difflib

# Below this similarity the "closest block" is noise, but we still say what the
# best score was instead of the bare "ensure EXACT match" that taught nothing.
_MIN_BLOCK_SIMILARITY = 0.25
_DIFF_CONTEXT_LINES = 3


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip())


def _has_tab_indent(lines: list[str]) -> bool:
    """Tabs make a column delta ambiguous — refuse to re-indent through them."""
    return any("\t" in line[: _indent_width(line)] for line in lines)


def reindent_block(text: str, delta: int) -> str | None:
    """Shift every non-blank line by *delta* columns. None if not possible.

    Removing indentation that is not there would change the block, so a line
    with fewer than ``-delta`` leading spaces aborts the whole repair.
    """
    lines = text.split("\n")
    if _has_tab_indent(lines):
        return None
    out = []
    for line in lines:
        if not line.strip():
            out.append(line)
        elif delta >= 0:
            out.append(" " * delta + line)
        elif _indent_width(line) < -delta:
            return None
        else:
            out.append(line[-delta:])
    return "\n".join(out)


def find_uniform_reindent(content: str, old_string: str) -> tuple[str, int] | None:
    """Locate *old_string* in *content* modulo a UNIFORM indentation shift.

    Returns ``(exact_block_as_it_appears_in_the_file, delta_columns)``, or None.

    Four cumulative guards, all of which must hold — in Python indentation IS
    semantics, so a non-uniform re-indent would silently move a ``return`` out
    of a loop or re-attach a ``finally`` to another ``try``:

    1. the block matches once leading whitespace is stripped from every line;
    2. that normalised match is UNIQUE in the whole file (not just the window);
    3. the column delta is identical on every non-blank line, and non-zero;
    4. no tab appears in any leading whitespace involved.

    Guard 4 (the caller re-indents ``new_string`` by the same delta) is enforced
    in ``_edit`` via :func:`reindent_block`, which refuses when impossible.
    """
    old_lines = old_string.split("\n")
    file_lines = content.split("\n")
    if not old_lines or len(old_lines) > len(file_lines):
        return None
    if _has_tab_indent(old_lines):
        return None

    key = [line.lstrip() for line in old_lines]
    starts = [
        i for i in range(len(file_lines) - len(old_lines) + 1)
        if [line.lstrip() for line in file_lines[i:i + len(old_lines)]] == key
    ]
    if len(starts) != 1:
        return None

    window = file_lines[starts[0]:starts[0] + len(old_lines)]
    if _has_tab_indent(window):
        return None
    deltas = {
        _indent_width(f) - _indent_width(o)
        for f, o in zip(window, old_lines) if o.strip()
    }
    if len(deltas) != 1:
        return None
    delta = deltas.pop()
    if delta == 0:
        return None
    return "\n".join(window), delta


def _closest_block(content: str, old_string: str) -> tuple[float, int]:
    """Return (similarity, 0-based start line) of the closest same-size block.

    The window is exactly ``len(old_lines)`` so the rendered diff aligns line for
    line. The old 0.4 floor is what kept 57 % of the failures silent: a 1-line
    ``old_string`` scored against a 1-line window rarely clears it, and 19 % of
    the silent set were single-line edits. The floor is 0.25 here, and even
    below it the caller still reports the number.
    """
    lines = content.split("\n")
    old_lines = old_string.split("\n")
    window = min(len(old_lines), len(lines))
    best_ratio, best_start = 0.0, 0
    for i in range(max(1, len(lines) - window + 1)):
        ratio = difflib.SequenceMatcher(
            None, old_string, "\n".join(lines[i:i + window])).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, i
    return best_ratio, best_start


def _render_line_diff(old_lines: list[str], block: list[str], first_lineno: int) -> tuple[str, int]:
    """Render the block diff, marking every diverging line with ``≠``.

    Returns ``(text, differing_line_count)``. ``-`` is what you sent, ``+`` is
    what the file actually holds.
    """
    rows: list[str] = []
    differing = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, block).get_opcodes():
        if tag == "equal":
            rows += [f"  {first_lineno + o:>5}    {block[o]}" for o in range(j1, j2)]
            continue
        differing += max(j2 - j1, i2 - i1)
        rows += [f"≠ {'':>5}  - {old_lines[o]}" for o in range(i1, i2)]
        rows += [f"≠ {first_lineno + o:>5}  + {block[o]}" for o in range(j1, j2)]
    return "\n".join(rows), differing


def describe_missing_old_string(content: str, old_string: str, file_path: str) -> str:
    """Explain WHY the edit missed: a line-level diff, never a bare sentence."""
    ratio, start = _closest_block(content, old_string)
    if ratio < _MIN_BLOCK_SIMILARITY:
        return (
            f"Error: old_string not found in {file_path}, and no similar block exists "
            f"(best similarity {ratio:.0%}). The file most likely no longer contains "
            f"anything close to it. Re-read it (Read symbol=... if you are aiming at a "
            f"function) before editing again. Do NOT re-send the same old_string."
        )
    lines = content.split("\n")
    old_lines = old_string.split("\n")
    end = min(len(lines), start + len(old_lines))
    body, differing = _render_line_diff(old_lines, lines[start:end], start + 1)
    before = [f"  {i + 1:>5}    {lines[i]}"
              for i in range(max(0, start - _DIFF_CONTEXT_LINES), start)]
    after = [f"  {i + 1:>5}    {lines[i]}"
             for i in range(end, min(len(lines), end + _DIFF_CONTEXT_LINES))]
    body = "\n".join(before + [body] + after)
    return (
        f"Error: old_string not found in {file_path}.\n"
        f"Closest block, lines {start + 1}-{end} (similarity {ratio:.0%}) — "
        f"{differing} line(s) out of {len(old_lines)} differ ('-' = what you sent, "
        f"'+' = what the file holds):\n\n{body}\n\n"
        f"The file differs from your context on the lines marked '≠'. Re-send Edit "
        f"with the '+' lines verbatim in old_string, OR target a shorter block that "
        f"avoids them."
    )
