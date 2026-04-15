# [desc] Incremental XML parser that extracts <tool_use> blocks from streamed text, honoring CDATA sections. [/desc]
"""Incremental XML parser that extracts <tool_use> blocks from streamed text.

The parser is driven by feed(chunk) calls. It returns the visible text (tool
XML stripped) and the list of complete tool calls discovered so far. CDATA
sections are honoured when scanning for end markers, so a Write payload that
contains </tool_use> or </param> inside CDATA does not confuse the scanner.

Errors never drop silently: malformed blocks become _XmlParseError tool calls
that the executor will translate to a tool_result the model can act on.
"""
from __future__ import annotations

import re

TOOL_OPEN_PREFIX = "<tool_use"
TOOL_CLOSE = "</tool_use>"
PARAM_OPEN_PREFIX = "<param"
PARAM_CLOSE = "</param>"
CDATA_START = "<![CDATA["
CDATA_END = "]]>"

_ATTR_RE = re.compile(r"""([A-Za-z_][\w-]*)\s*=\s*("[^"]*"|'[^']*')""")


def _max_prefix_suffix(buffer: str, target: str) -> int:
    """Length of the longest suffix of buffer that is a prefix of target.

    Used to decide how much of the buffer to hold back: a buffer ending in
    "<tool_us" must keep those 8 chars in case the next chunk completes a
    <tool_use opening, but a buffer ending in "Done." can be flushed entirely.
    """
    max_check = min(len(buffer), len(target) - 1)
    for k in range(max_check, 0, -1):
        if target.startswith(buffer[-k:]):
            return k
    return 0


def _find_skip_cdata(buf: str, target: str, start: int = 0) -> int:
    """Find target in buf starting from start, skipping over CDATA sections.

    Returns the index of the match, or -1 if not found (possibly because the
    current CDATA section is not yet closed in this buffer).
    """
    i = start
    while i < len(buf):
        if buf.startswith(CDATA_START, i):
            ce = buf.find(CDATA_END, i + len(CDATA_START))
            if ce == -1:
                return -1
            i = ce + len(CDATA_END)
            continue
        if buf.startswith(target, i):
            return i
        i += 1
    return -1


def _find_param_close(buf: str, start: int) -> int:
    """Find PARAM_CLOSE, skipping CDATA and nested <param>...</param> regions.

    A param body may legitimately contain a literal ``<param>...</param>`` (e.g.
    an Edit's new_string showing example XML). The naive first-match scan would
    treat the nested close as the outer param's close. We recurse instead.
    """
    i = start
    while i < len(buf):
        if buf.startswith(CDATA_START, i):
            ce = buf.find(CDATA_END, i + len(CDATA_START))
            if ce == -1:
                return -1
            i = ce + len(CDATA_END)
            continue
        if buf.startswith(PARAM_OPEN_PREFIX, i):
            attr_end = buf.find(">", i + len(PARAM_OPEN_PREFIX))
            if attr_end == -1:
                return -1
            inner_close = _find_param_close(buf, attr_end + 1)
            if inner_close == -1:
                return -1
            i = inner_close + len(PARAM_CLOSE)
            continue
        if buf.startswith(PARAM_CLOSE, i):
            return i
        i += 1
    return -1


def _find_tool_close(buf: str, start: int) -> int:
    """Find TOOL_CLOSE in buf, skipping CDATA sections AND <param>...</param> bodies.

    This keeps the outer tool_use framing robust when a param value contains
    a literal ``</tool_use>`` that the LLM forgot to wrap in CDATA: such a
    stray close tag inside a param body no longer terminates the outer block.
    """
    i = start
    while i < len(buf):
        if buf.startswith(CDATA_START, i):
            ce = buf.find(CDATA_END, i + len(CDATA_START))
            if ce == -1:
                return -1
            i = ce + len(CDATA_END)
            continue
        if buf.startswith(PARAM_OPEN_PREFIX, i):
            attr_end = buf.find(">", i + len(PARAM_OPEN_PREFIX))
            if attr_end == -1:
                return -1
            pe = _find_param_close(buf, attr_end + 1)
            if pe == -1:
                return -1
            i = pe + len(PARAM_CLOSE)
            continue
        if buf.startswith(TOOL_CLOSE, i):
            return i
        i += 1
    return -1


def _parse_attributes(attr_str: str):
    """Return {name: value} dict, or None if any non-whitespace part is unmatched."""
    out = {}
    pos = 0
    while pos < len(attr_str):
        if attr_str[pos].isspace():
            pos += 1
            continue
        m = _ATTR_RE.match(attr_str, pos)
        if m is None:
            return None
        out[m.group(1)] = m.group(2)[1:-1]
        pos = m.end()
    return out


_CANONICAL_SPLIT = CDATA_END + CDATA_START  # "]]><![CDATA[" — only emitted by our serializer


def _unwrap_cdata(value: str) -> str:
    """Concatenate text and CDATA-wrapped content into a single string.

    Tolerates LLM-emitted unescaped ``]]>`` inside a CDATA payload: when the
    value is a single CDATA section (no canonical split marker), we take
    everything from the first ``<![CDATA[`` to the LAST ``]]>``. The canonical
    serializer escape ``]]]]><![CDATA[>`` is still handled correctly because we
    detect the split marker and fall back to the multi-section scan.
    """
    stripped = value.strip()
    if (
        stripped.startswith(CDATA_START)
        and stripped.endswith(CDATA_END)
        and _CANONICAL_SPLIT not in stripped
    ):
        return stripped[len(CDATA_START):-len(CDATA_END)]

    parts = []
    i = 0
    while i < len(value):
        cs = value.find(CDATA_START, i)
        if cs == -1:
            parts.append(value[i:])
            break
        parts.append(value[i:cs])
        ce = value.find(CDATA_END, cs + len(CDATA_START))
        if ce == -1:
            parts.append(value[cs:])
            break
        parts.append(value[cs + len(CDATA_START):ce])
        i = ce + len(CDATA_END)
    return "".join(parts)


def _scan_params(body: str) -> dict:
    """Extract {name: value} from a sequence of <param name="...">value</param>."""
    params = {}
    i = 0
    while i < len(body):
        po = body.find(PARAM_OPEN_PREFIX, i)
        if po == -1:
            break
        attr_end = body.find(">", po + len(PARAM_OPEN_PREFIX))
        if attr_end == -1:
            break
        attr_str = body[po + len(PARAM_OPEN_PREFIX):attr_end]
        pe = _find_param_close(body, attr_end + 1)
        if pe == -1:
            break
        attrs = _parse_attributes(attr_str)
        if attrs and "name" in attrs:
            params[attrs["name"]] = _unwrap_cdata(body[attr_end + 1:pe])
        i = pe + len(PARAM_CLOSE)
    return params


def _make_error(msg: str, source: str) -> dict:
    return {
        "id": f"xmlerr_{abs(hash(source)) & 0xffffff:06x}",
        "name": "_XmlParseError",
        "input": {"_error": msg, "_source": source[:500]},
    }


def _parse_block(block: str) -> dict:
    """Parse a complete '<tool_use ...>...</tool_use>' string into a tool call dict."""
    if not block.startswith(TOOL_OPEN_PREFIX):
        return _make_error("internal: block does not start with <tool_use", block)
    attr_end = block.find(">", len(TOOL_OPEN_PREFIX))
    if attr_end == -1:
        return _make_error("malformed <tool_use> opening tag (no closing >)", block)
    attr_str = block[len(TOOL_OPEN_PREFIX):attr_end]
    if attr_str and not attr_str[0].isspace():
        return _make_error(
            "malformed <tool_use> opening tag (expected whitespace after <tool_use)",
            block,
        )
    attrs = _parse_attributes(attr_str)
    if attrs is None:
        return _make_error(
            f"malformed attributes in <tool_use>: {attr_str!r}",
            block,
        )
    name = attrs.get("name")
    if not name:
        return _make_error("<tool_use> missing required 'name' attribute", block)
    tool_id = attrs.get("id") or f"xml_{abs(hash(block)) & 0xffffff:06x}"
    body = block[attr_end + 1:-len(TOOL_CLOSE)]
    return {"id": tool_id, "name": name, "input": _scan_params(body)}


class XmlToolStreamParser:
    """Stateful, chunk-fed extractor of <tool_use> blocks from streamed text."""

    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: str) -> tuple[str, list[dict]]:
        self._buffer += chunk
        visible_parts: list[str] = []
        completed: list[dict] = []
        scan_from = 0
        while True:
            i = self._buffer.find(TOOL_OPEN_PREFIX, scan_from)
            if i == -1:
                hold = _max_prefix_suffix(self._buffer, TOOL_OPEN_PREFIX)
                emit_to = len(self._buffer) - hold
                text = self._buffer[:emit_to]
                stripped = text.rstrip('\n')
                nl_hold = len(text) - len(stripped)
                visible_parts.append(stripped)
                self._buffer = self._buffer[emit_to - nl_hold:]
                break
            next_pos = i + len(TOOL_OPEN_PREFIX)
            if next_pos >= len(self._buffer):
                text = self._buffer[:i]
                stripped = text.rstrip('\n')
                nl_hold = len(text) - len(stripped)
                visible_parts.append(stripped)
                self._buffer = self._buffer[i - nl_hold:]
                break
            next_char = self._buffer[next_pos]
            if not (next_char.isspace() or next_char == ">"):
                scan_from = next_pos
                continue
            visible_parts.append(self._buffer[:i].rstrip('\n'))
            self._buffer = self._buffer[i:]
            scan_from = 0
            close_at = _find_tool_close(self._buffer, len(TOOL_OPEN_PREFIX))
            if close_at == -1:
                break
            end = close_at + len(TOOL_CLOSE)
            block = self._buffer[:end]
            self._buffer = self._buffer[end:]
            completed.append(_parse_block(block))
        return "".join(visible_parts), completed

    def finalize(self) -> list[dict]:
        leftover = self._buffer
        self._buffer = ""
        if leftover.lstrip().startswith(TOOL_OPEN_PREFIX):
            return [_make_error(
                "unclosed <tool_use> block at end of stream", leftover
            )]
        return []
