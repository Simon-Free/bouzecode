# [desc] Incremental XML parser that extracts <tool_use> blocks from streamed text, honoring CDATA and backticks. [/desc]
"""Incremental XML parser that extracts <tool_use> blocks from streamed text.

The parser is driven by feed(chunk) calls. It returns the visible text (tool
XML stripped) and the list of complete tool calls discovered so far. CDATA
sections are honoured when scanning for end markers, so a Write payload that
contains </tool_use> or </param> inside CDATA does not confuse the scanner.

Content inside backtick code regions (`` inline or ```fenced blocks) is never
interpreted as tool XML — it passes through as visible text.

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
TOOL_RESULT_OPEN_PREFIX = "<tool_result"
TOOL_RESULT_CLOSE = "</tool_result>"

_ATTR_RE = re.compile(r"""([A-Za-z_][\w-]*)\s*=\s*("[^"]*"|'[^']*'|\[[^\]]*\])""")


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


# ---------------------------------------------------------------------------
# Backtick / code-region helpers
# ---------------------------------------------------------------------------

def _find_closing_fence(buf: str, start: int) -> int:
    """Find closing ``` fence starting search from *start*.

    The closing fence must be ``` at the start of a line.
    Returns index AFTER the closing fence line, or -1 if not found.
    """
    i = start
    while i < len(buf):
        if buf[i:i + 3] == '```' and (i == 0 or buf[i - 1] == '\n'):
            end_of_line = buf.find('\n', i + 3)
            return (end_of_line + 1) if end_of_line != -1 else len(buf)
        i += 1
    return -1


def _has_unclosed_fence(text: str) -> bool:
    """Return True if *text* ends inside an unclosed fenced code block."""
    in_fence = False
    i = 0
    while i < len(text):
        if text[i:i + 3] == '```' and (i == 0 or text[i - 1] == '\n'):
            in_fence = not in_fence
            nl = text.find('\n', i + 3)
            i = (nl + 1) if nl != -1 else len(text)
            continue
        i += 1
    return in_fence


def _has_unclosed_inline(text: str) -> int:
    """Return backtick count if *text* ends inside an unclosed inline code span, else 0."""
    i = 0
    while i < len(text):
        # Skip fenced blocks (handled separately)
        if text[i:i + 3] == '```' and (i == 0 or text[i - 1] == '\n'):
            nl = text.find('\n', i + 3)
            if nl == -1:
                return 0
            close = _find_closing_fence(text, nl + 1)
            if close == -1:
                return 0  # unclosed fence, not inline
            i = close
            continue
        if text[i] == '`':
            bt_count = 0
            j = i
            while j < len(text) and text[j] == '`':
                bt_count += 1
                j += 1
            if bt_count >= 1:
                close = text.find('`' * bt_count, j)
                if close == -1:
                    return bt_count  # unclosed inline code
                i = close + bt_count
                continue
            i = j
            continue
        i += 1
    return 0


def _is_in_thinking(buf: str, pos: int):
    """Check if *pos* in *buf* is inside a <thinking>...</thinking> block.

    Returns None if not inside thinking.
    Returns (skip_to,):
      - skip_to >= 0: thinking block ends here (position after </thinking>)
      - skip_to == -1: unclosed thinking block (extends to end of buffer)

    Only recognizes <thinking> as a real block opener when it appears at the
    start of a line (position 0 or preceded by newline). This avoids false
    positives from prose references like "use `<thinking>` blocks".
    """
    OPEN = "<thinking>"
    CLOSE = "</thinking>"
    i = 0
    while True:
        start = buf.find(OPEN, i)
        if start == -1 or start > pos:
            return None
        # Only treat as real thinking block if at start of line
        if start > 0 and buf[start - 1] != '\n':
            i = start + len(OPEN)
            continue
        # Find CLOSE tag that is at start of a line (col 0)
        search_from = start + len(OPEN)
        end = -1
        while True:
            candidate = buf.find(CLOSE, search_from)
            if candidate == -1:
                break
            if candidate == 0 or buf[candidate - 1] == '\n':
                end = candidate
                break
            search_from = candidate + len(CLOSE)
        if end == -1:
            # Unclosed thinking block
            if pos >= start:
                return (-1,)
            return None
        close_end = end + len(CLOSE)
        if pos >= start and pos < close_end:
            return (close_end,)
        i = close_end


def _is_in_code(buf: str, pos: int):
    """Check if *pos* in *buf* is inside a backtick code region.

    Returns None if not inside code.
    Returns (skip_to, region_start, is_fence):
      - skip_to >= 0: complete code region ends here
      - skip_to == -1: unclosed code region
      - region_start: where the code region begins
      - is_fence: whether it is a fenced block (vs inline)
    """
    i = 0
    while i < len(buf) and i <= pos:
        # Fenced code block: ``` at start of line
        if buf[i:i + 3] == '```' and (i == 0 or buf[i - 1] == '\n'):
            fence_start = i
            line_end = buf.find('\n', i + 3)
            if line_end == -1:
                return (-1, fence_start, True) if pos >= i else None
            close = _find_closing_fence(buf, line_end + 1)
            if close == -1:
                return (-1, fence_start, True) if pos >= i else None
            if pos < close:
                return (close, fence_start, True)
            i = close
            continue
        # Inline backticks (1+ protects against false tool_use parsing)
        if buf[i] == '`' and not (buf[i:i + 3] == '```' and (i == 0 or buf[i - 1] == '\n')):
            bt_start = i
            bt_count = 0
            j = i
            while j < len(buf) and buf[j] == '`':
                bt_count += 1
                j += 1
            if bt_count >= 1:
                close = buf.find('`' * bt_count, j)
                if close == -1:
                    return (-1, bt_start, False) if pos >= bt_start else None
                close_end = close + bt_count
                if pos >= bt_start and pos < close_end:
                    return (close_end, bt_start, False)
                i = close_end
                continue
            i = j
            continue
        # Indented code block (4+ spaces or tab at line start)
        if buf[i] == '\n' or i == 0:
            line_start = i + 1 if buf[i] == '\n' else i
            if line_start < len(buf):
                indent = 0
                while line_start + indent < len(buf) and buf[line_start + indent] == ' ':
                    indent += 1
                is_tab = line_start < len(buf) and buf[line_start] == '\t'
                if indent >= 4 or is_tab:
                    # Find end of indented block (next line without indent or end of buf)
                    block_start = line_start
                    scan = line_start
                    while scan < len(buf):
                        line_end = buf.find('\n', scan)
                        if line_end == -1:
                            line_end = len(buf)
                        line_indent = 0
                        while scan + line_indent < line_end and buf[scan + line_indent] == ' ':
                            line_indent += 1
                        is_line_tab = scan < line_end and buf[scan] == '\t'
                        is_blank = scan == line_end
                        if not is_blank and line_indent < 4 and not is_line_tab:
                            break
                        scan = line_end + 1 if line_end < len(buf) else line_end
                    if pos >= block_start and pos < scan:
                        return (scan, block_start, False)
                    if scan > i + 1:
                        i = scan
                        continue
        i += 1
    return None


# ---------------------------------------------------------------------------
# CDATA-aware scanning helpers
# ---------------------------------------------------------------------------

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
            if buf[attr_end - 1] == "/":  # self-closing <param .../> - no body to match
                i = attr_end + 1
                continue
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
            if buf[attr_end - 1] == "/":  # self-closing <param .../> - no body to skip
                i = attr_end + 1
                continue
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
        raw = m.group(2)
        out[m.group(1)] = raw if raw[0] == "[" else raw[1:-1]
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
        if attr_str.endswith("/"):  # self-closing <param name="x" value="y"/>
            attrs = _parse_attributes(attr_str[:-1])
            if attrs and "name" in attrs:
                params[attrs["name"]] = attrs.get("value", "")
            i = attr_end + 1
            continue
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
    input_params = _scan_params(body)
    if not input_params and body.strip():
        return _make_error(
            f"<tool_use name={name!r}> has body content but no <param> tags — "
            "LLM emitted malformed tool call",
            block,
        )
    for sched_key in ("depends_on", "tool_call_alias"):
        if sched_key in attrs and sched_key not in input_params:
            input_params[sched_key] = attrs[sched_key]
    return {"id": tool_id, "name": name, "input": input_params}


class XmlToolStreamParser:
    """Stateful, chunk-fed extractor of <tool_use> blocks from streamed text."""

    def __init__(self):
        self._buffer = ""
        self._in_fenced_block = False
        self._in_inline_code = 0  # 0 = not in inline code; >0 = backtick count to match
        self._in_thinking = False
        self._in_tool_result = False

    def feed(self, chunk: str) -> list[str | dict]:
        """Parse chunk, return interleaved list of visible text (str) and completed tools (dict)."""
        self._buffer += chunk
        result: list[str | dict] = []

        # --- Handle ongoing thinking block from a previous chunk ---
        if self._in_thinking:
            close_tag = "</thinking>"
            close = self._buffer.find(close_tag)
            if close == -1:
                # Still inside thinking — emit all as visible
                hold = _max_prefix_suffix(self._buffer, close_tag)
                emit_to = len(self._buffer) - hold
                text = self._buffer[:emit_to]
                if text:
                    result.append(text)
                self._buffer = self._buffer[emit_to:]
                return result
            # Found closing tag — emit thinking content as visible, exit thinking mode
            close_end = close + len(close_tag)
            text = self._buffer[:close_end]
            if text:
                result.append(text)
            self._buffer = self._buffer[close_end:]
            self._in_thinking = False

        # --- Handle ongoing tool_result block from a previous chunk ---
        if self._in_tool_result:
            close = self._buffer.find(TOOL_RESULT_CLOSE)
            if close == -1:
                # Still inside tool_result — swallow everything, hold partial close tag
                hold = _max_prefix_suffix(self._buffer, TOOL_RESULT_CLOSE)
                self._buffer = self._buffer[len(self._buffer) - hold:] if hold else ""
                return result
            # Found closing tag — discard everything up to and including it
            close_end = close + len(TOOL_RESULT_CLOSE)
            self._buffer = self._buffer[close_end:]
            self._in_tool_result = False

        # --- Handle ongoing fenced code block from a previous chunk ---
        if self._in_fenced_block:
            close = _find_closing_fence(self._buffer, 0)
            if close == -1:
                # Still inside fence — emit safe portion, hold back potential ``` prefix
                hold = _max_prefix_suffix(self._buffer, "\n```")
                emit_to = len(self._buffer) - hold
                text = self._buffer[:emit_to]
                if text:
                    result.append(text)
                self._buffer = self._buffer[emit_to:]
                return result
            # Emit fence content as visible, exit fenced mode
            text = self._buffer[:close]
            if text:
                result.append(text)
            self._buffer = self._buffer[close:]
            self._in_fenced_block = False

        # --- Handle ongoing inline code from a previous chunk ---
        if self._in_inline_code > 0:
            marker = '`' * self._in_inline_code
            close = self._buffer.find(marker)
            if close == -1:
                # Still inside inline code — emit all as visible, hold back potential ` suffix
                hold = _max_prefix_suffix(self._buffer, marker)
                emit_to = len(self._buffer) - hold
                text = self._buffer[:emit_to]
                if text:
                    result.append(text)
                self._buffer = self._buffer[emit_to:]
                return result
            # Emit inline code content as visible, exit inline code mode
            close_end = close + self._in_inline_code
            text = self._buffer[:close_end]
            if text:
                result.append(text)
            self._buffer = self._buffer[close_end:]
            self._in_inline_code = 0

        # --- Main scanning loop ---
        scan_from = 0
        while True:
            i_tool = self._buffer.find(TOOL_OPEN_PREFIX, scan_from)
            i_result = self._buffer.find(TOOL_RESULT_OPEN_PREFIX, scan_from)

            # Pick the earliest match; prefer tool_result if at same position
            # since <tool_result also starts with "<tool_" but is NOT a tool_use
            if i_result != -1 and (i_tool == -1 or i_result <= i_tool):
                # Check if this is really <tool_result (not <tool_resultXYZ)
                next_pos_r = i_result + len(TOOL_RESULT_OPEN_PREFIX)
                if next_pos_r < len(self._buffer):
                    next_char_r = self._buffer[next_pos_r]
                    if next_char_r.isspace() or next_char_r == ">":
                        # It's a <tool_result tag — swallow it
                        text_before = self._buffer[:i_result].rstrip('\n')
                        if text_before:
                            result.append(text_before)
                        # Find end of opening tag (the first > after <tool_result)
                        open_end = self._buffer.find(">", next_pos_r)
                        if open_end == -1:
                            # Incomplete opening tag — enter tool_result mode
                            self._buffer = self._buffer[i_result:]
                            self._in_tool_result = True
                            break
                        # Find closing </tool_result>
                        close = self._buffer.find(TOOL_RESULT_CLOSE, open_end + 1)
                        if close == -1:
                            # Incomplete — enter tool_result mode
                            self._buffer = self._buffer[i_result:]
                            self._in_tool_result = True
                            break
                        # Complete — discard the whole block
                        close_end = close + len(TOOL_RESULT_CLOSE)
                        self._buffer = self._buffer[close_end:]
                        scan_from = 0
                        continue
                elif next_pos_r == len(self._buffer):
                    # Buffer ends exactly at <tool_result — need more data
                    text_before = self._buffer[:i_result].rstrip('\n')
                    nl_hold = len(self._buffer[:i_result]) - len(text_before)
                    if text_before:
                        result.append(text_before)
                    self._buffer = self._buffer[i_result - nl_hold:]
                    break

            # Now handle <tool_use (original logic)
            # Recalculate i since we may not have matched tool_result
            i = self._buffer.find(TOOL_OPEN_PREFIX, scan_from)
            # Skip if this position is actually a <tool_result (already handled or not a valid tag)
            if i != -1 and self._buffer.startswith(TOOL_RESULT_OPEN_PREFIX, i):
                next_pos_r2 = i + len(TOOL_RESULT_OPEN_PREFIX)
                if next_pos_r2 < len(self._buffer):
                    ch = self._buffer[next_pos_r2]
                    if ch.isspace() or ch == ">":
                        scan_from = next_pos_r2
                        continue
                # Not a valid tool_result, treat as possible tool_use

            if i == -1:
                hold_tu = _max_prefix_suffix(self._buffer, TOOL_OPEN_PREFIX)
                hold_tr = _max_prefix_suffix(self._buffer, TOOL_RESULT_OPEN_PREFIX)
                hold = max(hold_tu, hold_tr)
                emit_to = len(self._buffer) - hold
                text = self._buffer[:emit_to]
                stripped = text.rstrip('\n')
                nl_hold = len(text) - len(stripped)
                if stripped:
                    result.append(stripped)
                self._buffer = self._buffer[emit_to - nl_hold:]
                # Track fenced/inline code state for next chunk
                if _has_unclosed_fence(stripped):
                    self._in_fenced_block = True
                else:
                    bt = _has_unclosed_inline(stripped)
                    if bt:
                        self._in_inline_code = bt
                break
            next_pos = i + len(TOOL_OPEN_PREFIX)
            if next_pos >= len(self._buffer):
                text = self._buffer[:i]
                stripped = text.rstrip('\n')
                nl_hold = len(text) - len(stripped)
                if stripped:
                    result.append(stripped)
                self._buffer = self._buffer[i - nl_hold:]
                # Track fenced/inline code state for next chunk
                if _has_unclosed_fence(stripped):
                    self._in_fenced_block = True
                else:
                    bt = _has_unclosed_inline(stripped)
                    if bt:
                        self._in_inline_code = bt
                break
            next_char = self._buffer[next_pos]
            if not (next_char.isspace() or next_char == ">"):
                scan_from = next_pos
                continue

            # --- Thinking block check ---
            thinking_info = _is_in_thinking(self._buffer, i)
            if thinking_info is not None:
                skip_to = thinking_info[0]
                if skip_to >= 0:
                    scan_from = skip_to
                    continue
                # Unclosed thinking block — emit everything as visible
                text = self._buffer.rstrip('\n')
                if text:
                    result.append(text)
                self._buffer = ""
                self._in_thinking = True
                break

            # --- Code region check ---
            code_info = _is_in_code(self._buffer, i)
            if code_info is not None:
                skip_to, region_start, is_fence = code_info
                if skip_to >= 0:
                    # Complete code region — skip past it
                    scan_from = skip_to
                    continue
                # Unclosed code region
                if is_fence:
                    # Emit text before fence normally, then fence content as visible
                    text_before = self._buffer[:region_start].rstrip('\n')
                    if text_before:
                        result.append(text_before)
                    fence_text = self._buffer[region_start:]
                    if fence_text:
                        result.append(fence_text)
                    self._buffer = ""
                    self._in_fenced_block = True
                else:
                    # Unclosed inline code — emit including backticks as visible, track state
                    bt_count = 0
                    j = region_start
                    while j < len(self._buffer) and self._buffer[j] == '`':
                        bt_count += 1
                        j += 1
                    text = self._buffer.rstrip('\n')
                    if text:
                        result.append(text)
                    self._buffer = ""
                    self._in_inline_code = bt_count
                break

            # --- Normal tool_use processing ---
            text = self._buffer[:i].rstrip('\n')
            if text:
                result.append(text)
            self._buffer = self._buffer[i:]
            scan_from = 0
            close_at = _find_tool_close(self._buffer, len(TOOL_OPEN_PREFIX))
            if close_at == -1:
                break
            end = close_at + len(TOOL_CLOSE)
            block = self._buffer[:end]
            self._buffer = self._buffer[end:]
            result.append(_parse_block(block))
            self._buffer = self._buffer.lstrip('\n')
        return result

    def finalize(self) -> list[dict]:
        leftover = self._buffer
        self._buffer = ""
        if self._in_fenced_block:
            return []
        if leftover.lstrip().startswith(TOOL_OPEN_PREFIX):
            # Check if inside an inline code region
            stripped = leftover.lstrip()
            tool_pos = len(leftover) - len(stripped)
            if _is_in_code(leftover, tool_pos) is not None:
                return []
            return [_make_error(
                "unclosed <tool_use> block at end of stream", leftover
            )]
        return []
