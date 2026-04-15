# [desc] Cleans raw terminal output by stripping ANSI codes, spinners, and carriage-return overwrites. [/desc]
"""Clean raw terminal output (ANSI, spinner, \\r overwrite) for web display."""
from __future__ import annotations

import re

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07")
SPINNER_RE = re.compile(r"^\s*[\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f]")


def clean_stdout(raw: str) -> str:
    """Process raw terminal output for web display: simulate \\r, strip ANSI, filter spinners."""
    out: list[str] = []
    for line in raw.split("\n"):
        segments = line.split("\r")
        visible = next((s for s in reversed(segments) if s.strip()), "")
        clean = ANSI_RE.sub("", visible).rstrip()
        if not clean or SPINNER_RE.match(clean):
            continue
        out.append(clean)
    return "\n".join(out)
