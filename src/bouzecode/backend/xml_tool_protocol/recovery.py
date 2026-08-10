# [desc] End-of-stream repair of the model's frequent `"> instead of </param>` slip, plus a targeted diagnostic naming the tool and param left open. [/desc]
"""Best-effort repair of malformed <tool_use> XML, applied at END OF STREAM only.

Two recoveries, both unambiguous because they are only attempted once the strict
parser has already given up on the trailing buffer (see XmlToolStreamParser.finalize):

1. **Quote slip** — the model closes a param value the way it would close an
   attribute: ``...value"><param name="next">`` instead of ``...value</param>``.
   The sequence ``">`` is only rewritten to ``</param>`` when it sits inside an
   open param body AND is immediately followed by a real ``<param name="...">``
   opening tag or by ``</tool_use>``.
2. **Missing </tool_use>** — a new ``<tool_use name="...">`` opens while the
   previous one is still open *at param level 0*.  A ``<tool_use>`` found inside
   an open param body is NEVER treated this way: it is legitimate example XML in
   a value, and splitting there would execute documentation as a tool call.

Every repair is reported back as a note so the caller can log it: recovery must
stay visible, never silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CDATA_START = "<![CDATA["
CDATA_END = "]]>"
PARAM_CLOSE = "</param>"
TOOL_CLOSE = "</tool_use>"
QUOTE_SLIP = '">'

_PARAM_OPEN_RE = re.compile(r"<param(\s[^>]*)?>")
_TOOL_OPEN_RE = re.compile(r"<tool_use(\s[^>]*)?>")
_NAME_ATTR_RE = re.compile(r'\bname\s*=\s*"([^"]*)"')
_ID_ATTR_RE = re.compile(r'\bid\s*=\s*"([^"]*)"')
# An opening <param ... name="x" that the stream cut before its closing '>'.
_PARTIAL_PARAM_RE = re.compile(r'<param\s[^>]*?name\s*=\s*"([^"]*)"?[^>]*$')


@dataclass
class TailState:
    """What the walker was looking at when the text ran out."""

    tool_name: str | None = None
    tool_id: str | None = None
    open_params: list[str] = field(default_factory=list)


def _param_open_at(text: str, i: int):
    """Return (end, name, self_closing) if a real <param name="..."> starts at i."""
    m = _PARAM_OPEN_RE.match(text, i)
    if m is None:
        return None
    attrs = m.group(1) or ""
    nm = _NAME_ATTR_RE.search(attrs)
    if nm is None:
        return None
    return m.end(), nm.group(1), attrs.rstrip().endswith("/")


def _tool_open_at(text: str, i: int):
    """Return (end, name, id) if a real <tool_use name="..."> starts at i."""
    m = _TOOL_OPEN_RE.match(text, i)
    if m is None:
        return None
    attrs = m.group(1) or ""
    nm = _NAME_ATTR_RE.search(attrs)
    if nm is None:
        return None
    id_m = _ID_ATTR_RE.search(attrs)
    return m.end(), nm.group(1), (id_m.group(1) if id_m else None)


_TAG_LOOKBACK = 512


def _terminates_an_opening_tag(text: str, quote: int) -> bool:
    """True if the `">` at *quote* closes a `<... attr="v">` tag rather than a value.

    A value may legitimately quote example XML — ``<tool_use name="Bash" id="b9">``
    also ends with ``">`` and is immediately followed by ``<param name=``. Walking
    back to the nearest unbalanced ``<`` tells the two apart.
    """
    start = max(0, quote - _TAG_LOOKBACK)
    for j in range(quote - 1, start - 1, -1):
        if text[j] == ">":
            return False
        if text[j] == "<":
            return True
    return False


def _slip_ends_a_param(text: str, quote: int) -> bool:
    """True if a `">` can only be a mis-closed param, never a value or a tag."""
    if _terminates_an_opening_tag(text, quote):
        return False
    pos = quote + len(QUOTE_SLIP)
    return text.startswith(TOOL_CLOSE, pos) or _param_open_at(text, pos) is not None


def _scan(text: str, repair: bool) -> tuple[str, list[str], TailState]:
    state = TailState()
    pieces: list[str] = []
    notes: list[str] = []
    last = 0
    i = 0
    while i < len(text):
        if text.startswith(CDATA_START, i):
            end = text.find(CDATA_END, i + len(CDATA_START))
            i = len(text) if end == -1 else end + len(CDATA_END)
            continue
        if state.open_params:
            if text.startswith(PARAM_CLOSE, i):
                state.open_params.pop()
                i += len(PARAM_CLOSE)
                continue
            if text.startswith(QUOTE_SLIP, i) and _slip_ends_a_param(text, i):
                notes.append(
                    f'<tool_use name="{state.tool_name}"> param '
                    f'"{state.open_params[-1]}" closed with \'">\' instead of </param>'
                )
                if repair:
                    pieces.append(text[last:i])
                    pieces.append(PARAM_CLOSE)
                    last = i + len(QUOTE_SLIP)
                state.open_params.pop()
                i += len(QUOTE_SLIP)
                continue
            opened = _param_open_at(text, i)
            if opened is not None:
                end, name, self_closing = opened
                if not self_closing:
                    state.open_params.append(name)
                i = end
                continue
            i += 1
            continue
        if text.startswith(TOOL_CLOSE, i):
            state.tool_name = None
            state.tool_id = None
            i += len(TOOL_CLOSE)
            continue
        tool = _tool_open_at(text, i)
        if tool is not None:
            end, name, tool_id = tool
            if state.tool_name is not None:
                notes.append(
                    f'<tool_use name="{state.tool_name}"> missing its </tool_use> '
                    f'before <tool_use name="{name}">'
                )
                if repair:
                    pieces.append(text[last:i])
                    pieces.append(TOOL_CLOSE)
                    last = i
            state.tool_name = name
            state.tool_id = tool_id
            i = end
            continue
        opened = _param_open_at(text, i) if state.tool_name is not None else None
        if opened is not None:
            end, name, self_closing = opened
            if not self_closing:
                state.open_params.append(name)
            i = end
            continue
        i += 1
    pieces.append(text[last:])
    return "".join(pieces), notes, state


def repair_tail(text: str) -> tuple[str, list[str]]:
    """Return (repaired_text, notes). notes is empty when nothing was rewritten."""
    repaired, notes, _ = _scan(text, repair=True)
    return repaired, notes


def _open_tool_label(state: TailState) -> str:
    if state.tool_name is None:
        return "<tool_use>"
    id_part = f' id="{state.tool_id}"' if state.tool_id else ""
    return f'<tool_use name="{state.tool_name}"{id_part}>'


def describe_unclosed_tail(text: str) -> str:
    """Diagnostic naming the tool and, when known, the param left open."""
    _, _, state = _scan(text, repair=False)
    label = _open_tool_label(state)
    param = state.open_params[-1] if state.open_params else None
    if param is None:
        partial = _PARTIAL_PARAM_RE.search(text)
        param = partial.group(1) if partial else None
    if param is not None:
        return (
            f'unclosed {label}: <param name="{param}"> is never closed — the stream '
            f'ended inside it. Re-emit ONLY this tool call, closing the param with '
            f'</param> (not with \'">\').'
        )
    return (
        f"unclosed {label} block at end of stream: </tool_use> is missing. "
        f"Re-emit ONLY this tool call."
    )
