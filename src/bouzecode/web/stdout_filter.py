# [desc] Converts raw terminal output with ANSI codes to styled HTML spans for web display [/desc]
"""Convert raw terminal output (ANSI codes, spinner, \\r overwrite) to HTML for web display."""
from __future__ import annotations

import re
from html import escape

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07")
SPINNER_RE = re.compile(r"^\s*[\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f]")

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_OSC_RE = re.compile(r"\x1b\].*?\x07")

_FG_COLORS = {
    30: "black", 31: "red", 32: "green", 33: "yellow",
    34: "blue", 35: "magenta", 36: "cyan", 37: "white",
    90: "bright-black", 91: "bright-red", 92: "bright-green", 93: "bright-yellow",
    94: "bright-blue", 95: "bright-magenta", 96: "bright-cyan", 97: "bright-white",
}
_BG_COLORS = {
    40: "black", 41: "red", 42: "green", 43: "yellow",
    44: "blue", 45: "magenta", 46: "cyan", 47: "white",
    100: "bright-black", 101: "bright-red", 102: "bright-green", 103: "bright-yellow",
    104: "bright-blue", 105: "bright-magenta", 106: "bright-cyan", 107: "bright-white",
}


def _state_to_spans(state: dict) -> list[str]:
    """Generate opening span tags for the current terminal state."""
    spans = []
    if state["bold"]:
        spans.append('<span class="ansi-bold">')
    if state["dim"]:
        spans.append('<span class="ansi-dim">')
    if state["italic"]:
        spans.append('<span class="ansi-italic">')
    if state["underline"]:
        spans.append('<span class="ansi-underline">')
    if state["fg"]:
        spans.append(f'<span class="ansi-fg-{state["fg"]}">')
    if state["bg"]:
        spans.append(f'<span class="ansi-bg-{state["bg"]}">')
    return spans


def ansi_line_to_html(line: str) -> str:
    """Convert a single line with ANSI codes to HTML with span classes."""
    line = _OSC_RE.sub("", line)
    result: list[str] = []
    open_spans = 0
    last_end = 0
    state = {"bold": False, "dim": False, "italic": False, "underline": False, "fg": None, "bg": None}

    for match in _SGR_RE.finditer(line):
        start, end = match.span()
        if start > last_end:
            result.append(escape(line[last_end:start]))
        last_end = end

        params_str = match.group(1)
        if not params_str:
            codes = [0]
        else:
            codes = [int(c) for c in params_str.split(";") if c]

        new_state = state.copy()
        for code in codes:
            if code == 0:
                new_state = {"bold": False, "dim": False, "italic": False, "underline": False, "fg": None, "bg": None}
            elif code == 1:
                new_state["bold"] = True
            elif code == 2:
                new_state["dim"] = True
            elif code == 3:
                new_state["italic"] = True
            elif code == 4:
                new_state["underline"] = True
            elif code in _FG_COLORS:
                new_state["fg"] = _FG_COLORS[code]
            elif code in _BG_COLORS:
                new_state["bg"] = _BG_COLORS[code]

        if new_state != state:
            result.append("</span>" * open_spans)
            open_spans = 0
            state = new_state
            spans = _state_to_spans(state)
            result.extend(spans)
            open_spans = len(spans)

    if last_end < len(line):
        result.append(escape(line[last_end:]))

    result.append("</span>" * open_spans)
    return "".join(result)


def clean_stdout(raw: str) -> str:
    """Process raw terminal output for web display: simulate \\r, convert ANSI to HTML, filter spinners."""
    out: list[str] = []
    for line in raw.split("\n"):
        segments = line.split("\r")
        visible = next((s for s in reversed(segments) if s.strip()), "")
        html = ansi_line_to_html(visible).rstrip()
        plain = ANSI_RE.sub("", visible).strip()
        if not plain or SPINNER_RE.match(plain):
            continue
        out.append(html)
    return "\n".join(out)
