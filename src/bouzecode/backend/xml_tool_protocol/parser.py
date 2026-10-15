# [desc] Incremental XML parser that extracts <tool_use> blocks from streamed text, honoring CDATA and backticks. [/desc]
"""Incremental XML parser that extracts <tool_use> blocks from streamed text.

The parser is driven by feed(chunk) calls. It returns the visible text (tool
XML stripped) and the list of complete tool calls discovered so far. CDATA
sections are honoured when scanning for end markers, so a Write payload that
contains </tool_use> or </param> inside CDATA does not confuse the scanner.

Content inside backtick code regions (`` inline or ```fenced blocks) is never
interpreted as tool XML — it passes through as visible text.

Errors never drop silently: malformed blocks become _XmlParseError tool calls
that the executor will translate to a tool_result the model can act on. The one
exception is a <tool_use> carrying neither a `name` attribute nor any <param>:
that is never a call the model could have meant, only prose quoting the tag, so
it stays visible text (see _is_prose_mention).
"""
from __future__ import annotations

import json
import logging
import re

from .recovery import describe_unclosed_tail, repair_tail

_log = logging.getLogger(__name__)

TOOL_OPEN_PREFIX = "<tool_use"
TOOL_CLOSE = "</tool_use>"
PARAM_OPEN_PREFIX = "<param"
PARAM_CLOSE = "</param>"
CDATA_START = "<![CDATA["
CDATA_END = "]]>"
TOOL_RESULT_OPEN_PREFIX = "<tool_result"
TOOL_RESULT_CLOSE = "</tool_result>"

# Batch wrapper. Every tool_use of a turn lives inside one <tool_calls> block, and
# TOOL_CALLS_STOP is sent to the API as a stop sequence: generation is cut at the
# closing tag, so the model physically cannot write a "Tool result" of its own
# invention afterwards (the failure mode of session 178666a6).
TOOL_CALLS_OPEN = "<tool_calls>"
TOOL_CALLS_CLOSE = "</tool_calls>"
TOOL_CALLS_STOP = TOOL_CALLS_CLOSE

# Any suffix of these tags is held back until the next chunk resolves it: a
# wrapper tag split across SSE chunks — even the lone "<" — must never leak
# into visible text (session f52cb5297f4f: 115+ messages with "ool_calls>"
# fragments). A pending that never resolves is flushed as plain text by
# finalize(), so ordinary prose ending on "<" is not swallowed.
_WRAPPER_TAGS = (TOOL_CALLS_OPEN, TOOL_CALLS_CLOSE)

# A turn that produced no tool call, yet looks like the model *believed* it called
# one: markdown/JSON imitation of the native protocol, or a fabricated result.
_FAKE_CALL_MARKERS = ("**tool call:**", "**tool result:**", "**tool_call:**")
_FAKE_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\{.*?\}\s*```", re.DOTALL)
_FAKE_ARG_KEYS = ('"args"', '"arguments"', '"parameters"', "'args'", "'arguments'")
_SEEN_TEXT_LIMIT = 20_000

_FAKE_FORMAT_ERROR = (
    "No tool was called this turn, but your text imitates a tool call "
    "(markdown/JSON block, `**Tool call:**`, or a `**Tool result:**` you wrote "
    "yourself). Prose executes NOTHING and a result you write is a hallucination. "
    "Re-emit the call as XML inside the batch wrapper: "
    '<tool_calls><tool_use name="ToolName" id="x1"><param name="key">value</param>'
    "</tool_use></tool_calls> — then stop and wait for the real result."
)

# An attribute value is a quoted string, a bare JSON array, or a JSON array that
# the model wrapped in quotes anyway — depends_on="["w1"]", by far its most
# frequent slip (family I.a of docs/investigations/xml_tool_call_failures.md).
# The quoted-array alternative MUST come first: on depends_on="["w1"]" the plain
# "[^"]*" alternative matches only `"["` and leaves `w1"]"` dangling, which is
# precisely why the whole call used to be rejected.
# The last alternative recovers an UNTERMINATED bare array (depends_on=["w1"
# with the closing ] lost before >): it stops before any > so it can never run
# past the end of the opening tag, and _parse_attributes closes it back.
_ATTR_RE = re.compile(
    r"""([A-Za-z_][\w-]*)\s*=\s*("\[[^\]]*\]"|"[^"]*"|'[^']*'|\[[^\]]*\]|\[[^\]>]*)"""
)

# A real <param> tag inside a block body — the marker that tells a genuine tool
# call apart from prose merely quoting the <tool_use> tag.
_PARAM_NAME_IN_BODY = re.compile(r"<param\s[^>]*\bname\s*=")


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


def _text_for_code_tracking(text: str) -> tuple[str, bool]:
    """Strip <thinking>...</thinking> regions from *text* for code-state tracking.

    Returns (clean_text, enters_thinking):
      - clean_text: text with closed thinking regions removed
      - enters_thinking: True if text ends inside an unclosed thinking block
    """
    OPEN = "<thinking>"
    CLOSE = "</thinking>"
    parts: list[str] = []
    i = 0
    while True:
        start = text.find(OPEN, i)
        if start == -1:
            parts.append(text[i:])
            return ("".join(parts), False)
        # Only treat as real thinking block if at start of line
        if start > 0 and text[start - 1] != '\n':
            parts.append(text[i:start + len(OPEN)])
            i = start + len(OPEN)
            continue
        # Real thinking opener
        parts.append(text[i:start])
        # Find matching close (at start of line)
        search_from = start + len(OPEN)
        end = -1
        while True:
            candidate = text.find(CLOSE, search_from)
            if candidate == -1:
                break
            if candidate == 0 or text[candidate - 1] == '\n':
                end = candidate
                break
            search_from = candidate + len(CLOSE)
        if end == -1:
            # Unclosed thinking — everything from <thinking> onward is thinking
            return ("".join(parts), True)
        # Closed thinking — skip the whole region
        i = end + len(CLOSE)
    # unreachable but keeps mypy happy
    return ("".join(parts), False)


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

    A param body may legitimately contain literal angle brackets including
    ``<param>`` or ``</param>`` (e.g. an Edit showing example XML).  We only
    treat a ``<param`` occurrence as a *real* nested tag if its attribute string
    contains a valid ``name="..."`` attribute — the mandatory attribute for our
    protocol.  Bare ``<param>`` without ``name=`` is literal text.

    Note: the only case that STILL requires CDATA wrapping is a value that
    contains the exact sequence ``</param>`` immediately followed by
    ``</tool_use>`` or another ``<param name=`` — i.e. something
    indistinguishable from real protocol framing.
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
                # Unclosed angle bracket — treat as literal text, advance past '<'
                i += 1
                continue
            attr_str = buf[i + len(PARAM_OPEN_PREFIX):attr_end]
            # A *real* nested param tag must have a name="..." attribute.
            # If it doesn't, this is just literal text containing '<param'.
            is_self_closing = attr_str.endswith("/")
            attr_to_parse = attr_str[:-1] if is_self_closing else attr_str
            attrs = _parse_attributes(attr_to_parse) if attr_to_parse.strip() else {}
            if attrs is None or "name" not in (attrs or {}):
                # Not a real param tag — literal text, skip past the '<'
                i += 1
                continue
            if is_self_closing:
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

    Only ``<param`` occurrences with a valid ``name="..."`` attribute are
    treated as real param tags whose body is skipped.  Bare angle-bracket
    sequences are treated as literal text.
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
                # Unclosed — treat as literal, skip past '<'
                i += 1
                continue
            attr_str = buf[i + len(PARAM_OPEN_PREFIX):attr_end]
            is_self_closing = attr_str.endswith("/")
            attr_to_parse = attr_str[:-1] if is_self_closing else attr_str
            attrs = _parse_attributes(attr_to_parse) if attr_to_parse.strip() else {}
            if attrs is None or "name" not in (attrs or {}):
                # Not a real param tag — literal text
                i += 1
                continue
            if is_self_closing:
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
            # One unparsable fragment must NOT cost the whole tool call: skip it
            # up to the next whitespace and keep reading the other attributes.
            # 'name' stays required in _parse_block, so prose is still filtered.
            while pos < len(attr_str) and not attr_str[pos].isspace():
                pos += 1
            continue
        raw = m.group(2)
        # A bare [..] keeps its brackets; every quoted form drops its quotes, so
        # depends_on=["w1"] and depends_on="["w1"]" both yield the string ["w1"]
        # that _coerce_list already knows how to read. An unterminated bare list
        # keeps the bracket it lost, so it stays readable all the same.
        if raw[0] == "[":
            out[m.group(1)] = raw if raw.endswith("]") else raw + "]"
        else:
            out[m.group(1)] = raw[1:-1]
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


def _is_prose_mention(block: str) -> bool:
    """True when a <tool_use ...> is the model TALKING about the protocol.

    `name` is mandatory, so a block without it can never be executed. The old
    reaction — an _XmlParseError — is the most expensive one available: it is a
    fake tool call, so the executor answers it and the model pays a full API
    round-trip. The measurement in docs/investigations/xml_tool_call_failures.md
    found that family (36 % of all parse errors historically) to be prose,
    typically `<tool_use>` quoted between backticks. Not treating it as a call at
    all is the cheapest correct answer: the text simply stays visible.

    The guard is narrow on purpose. Prose = NO attribute at all AND no
    `<param name=...>` in the body. A block that lost only its `name` while still
    carrying params is a genuine call gone wrong, and it must keep its error
    rather than disappear in silence.
    """
    attr_end = block.find(">", len(TOOL_OPEN_PREFIX))
    if attr_end == -1:
        return False
    return (
        not block[len(TOOL_OPEN_PREFIX):attr_end].strip()
        and _PARAM_NAME_IN_BODY.search(block, attr_end) is None
    )


def _coerce_sched_list(raw):
    """Turn a scheduling attribute into a real list of aliases.

    ``depends_on`` is documented as a JSON array, but it reaches us as raw text
    (_parse_attributes stays type-agnostic on purpose). Leaving the string in the
    call ``input`` made the TUI print ``depends_on="["w1"]"`` while the DAG worked,
    because dag._coerce_list re-decoded it much later. Decoding here gives every
    consumer the same value; _coerce_list already accepts a list unchanged.
    """
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text.startswith("["):
        # A bare attribute list (depends_on="push1,w1") names several aliases: split it.
        # Only a malformed ARRAY is left unsplit (see below).
        return [part.strip() for part in text.split(",") if part.strip()]
    try:
        decoded = json.loads(text)
    except ValueError:
        # An unreadable array must stay READABLE as text: inventing aliases by
        # splitting on commas would fabricate dependencies that never existed.
        return raw
    if isinstance(decoded, list):
        return [str(item) for item in decoded if str(item).strip()]
    return [str(decoded)]


def _parse_block(block: str):
    """Parse '<tool_use ...>...</tool_use>' into a tool call dict.

    Returns None when the block is not a call at all (see _is_prose_mention).
    """
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
        if _is_prose_mention(block):
            return None
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
            value = attrs[sched_key]
            if sched_key == "depends_on":
                value = _coerce_sched_list(value)
            input_params[sched_key] = value
    return {"id": tool_id, "name": name, "input": input_params}


def _top_level_spans(text: str) -> tuple[list[tuple[int, int]], bool]:
    """Split text into the spans that sit OUTSIDE any tool_use block.

    Everything inside a ``<tool_use ...>...</tool_use>`` block is payload the
    model authored on purpose — including a literal mention of the batch wrapper
    inside a param body or a CDATA section — and must survive verbatim.
    ``_find_tool_close`` already skips CDATA and param bodies, and returns -1
    when the block is still open, in which case the tail is left untouched and
    the caller is told a call is open (second element of the tuple).
    """
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        j = text.find(TOOL_OPEN_PREFIX, i)
        if j == -1:
            spans.append((i, n))
            return spans, False
        if j > i:
            spans.append((i, j))
        close = _find_tool_close(text, j + len(TOOL_OPEN_PREFIX))
        if close == -1:
            return spans, True
        i = close + len(TOOL_CLOSE)
    return spans, False


def _drop_wrapper_tag(seg: str, tag: str, before: str) -> str:
    """Remove ``tag`` from ``seg`` except where a backtick right before it says it is
    CODE the model is citing (`` `</tool_calls>` ``): erasing it there left an empty
    pair of backticks, read as an unclosed inline code span that swallowed the calls
    written after it."""
    out, i = [], 0
    while True:
        j = seg.find(tag, i)
        if j == -1:
            out.append(seg[i:])
            return "".join(out)
        prev = seg[j - 1] if j > 0 else before
        out.append(seg[i:j])
        if prev == "`":
            out.append(tag)
        i = j + len(tag)


def _strip_wrapper_tags(text: str, offset: int = 0, before: str = "") -> tuple[str, str, bool]:
    """Remove the batch wrapper tags OUTSIDE tool calls, holding a partial tail.

    The wrapper is pure framing: it is never visible text and never a tool call.
    But a wrapper tag quoted INSIDE a call (a Write param carrying protocol
    documentation, a test, a regex) is content: stripping it there corrupted the
    param silently. So the removal is now contextual, and the closing tag only
    counts as "the batch ended" when it is seen at top level.

    ``text`` may start with already-parsed residue (the parser buffer) so that an
    open call is visible; ``offset`` says where the NEW text begins. Only that
    part is returned.
    Returns (cleaned_new_text, pending_suffix_for_next_chunk, closed_at_top).
    """
    spans, call_open = _top_level_spans(text)
    pieces: list[str] = []
    closed = False
    prev = offset
    for start, end in spans:
        if end <= offset:
            continue
        start = max(start, offset)
        pieces.append(text[prev:start])
        seg = text[start:end]
        if TOOL_CALLS_CLOSE in seg:
            closed = True
        seg_before = text[start - 1] if start > 0 else before
        for tag in _WRAPPER_TAGS:
            if tag in seg:
                seg = _drop_wrapper_tag(seg, tag, seg_before)
        pieces.append(seg)
        prev = end
    pieces.append(text[prev:])
    cleaned = "".join(pieces)
    if call_open:
        # A trailing '<' belongs to the call being written, not to the wrapper.
        return cleaned, "", closed
    hold = 0
    for tag in _WRAPPER_TAGS:
        n = _max_prefix_suffix(cleaned, tag)
        if n >= 1 and n > hold:
            hold = n
    if not hold:
        return cleaned, "", closed
    return cleaned[:len(cleaned) - hold], cleaned[len(cleaned) - hold:], closed


_QUOTE_OPENERS = "\"'«“‘`"
_QUOTE_CLOSERS = "\"'»”’`"
_QUOTE_GAP = "   "


def _is_quoted(text: str, start: int, end: int) -> bool:
    """True when text[start:end] sits between a quote pair (``"…"``, ``« … »``, ``'…'``,
    ``“…”``), blanks allowed on each side: a tag QUOTED in prose, not written."""
    i = start - 1
    while i >= 0 and text[i] in _QUOTE_GAP and start - i <= 2:
        i -= 1
    j = end
    while j < len(text) and text[j] in _QUOTE_GAP and j - end < 2:
        j += 1
    return (i >= 0 and text[i] in _QUOTE_OPENERS
            and j < len(text) and text[j] in _QUOTE_CLOSERS)


def _masked_calls(text: str) -> tuple[str, list[int]]:
    """``text`` with every tool_use block blanked out (``x``, newlines kept) and the end
    offsets of the COMPLETE blocks. Backticks, quotes or thinking tags inside a param
    are payload: they must not decide whether the prose around the calls is code."""
    spans, _ = _top_level_spans(text)
    chars = list(text)
    ends: list[int] = []
    prev = 0
    for start, end in spans + [(len(text), len(text))]:
        for k in range(prev, start):
            if chars[k] != "\n":
                chars[k] = "x"
        if start > prev and text.endswith(TOOL_CLOSE, 0, start):
            ends.append(start)
        prev = end
    return "".join(chars), ends


def _written_tag_positions(masked: str, tag: str) -> list[int]:
    """Occurrences of ``tag`` that are WRITTEN, not cited: outside a thinking block,
    outside code (inline backticks, fence, indented block), outside quotes."""
    found = []
    at = masked.find(tag)
    while at != -1:
        if (_is_in_thinking(masked, at) is None and _is_in_code(masked, at) is None
                and not _is_quoted(masked, at, at + len(tag))):
            found.append(at)
        at = masked.find(tag, at + 1)
    return found


def _is_real_batch_close(raw: str) -> bool:
    """A batch really closed in ``raw`` (the model's text so far): a written closing tag
    preceded by a written opening tag — or, historical tolerance, by a complete call.

    Session a3b38124: « arrêt volontaire sur </tool_calls> » in a <thinking> was taken
    for the end of the batch; the client hung up mid-reasoning and the turn was lost."""
    masked, call_ends = _masked_calls(raw)
    closes = _written_tag_positions(masked, TOOL_CALLS_CLOSE)
    if not closes:
        return False
    opens = _written_tag_positions(masked, TOOL_CALLS_OPEN)
    return any(
        any(o < c for o in opens) or any(e <= c for e in call_ends)
        for c in closes
    )


def _drop_orphan_wrapper_suffix(text):
    """Drop a wrapper tag TAIL that arrives with its head already gone.

    The gateway applies our cut marker across two SSE deltas: it swallows the
    delta holding the first characters of the closing wrapper tag, then forwards
    the remainder alone (session 46cf0a617b4c: 5 assistant messages whose whole
    visible text was that orphan remainder). The client never saw the tag start,
    so no hold could apply and the leftovers leaked as prose. Only a suffix of at
    least 5 chars is dropped, and every candidate ends on the closing chevron, so
    ordinary prose can never match.
    """
    for tag in _WRAPPER_TAGS:
        for k in range(len(tag) - 1, 4, -1):
            if text.startswith(tag[-k:]):
                return text[k:]
    # The remainder does not always start the delta: the gateway forwards the end
    # of the prose and the orphan tail together, so the residue sits at the END,
    # alone on its line (TUI showed a bare "ool_calls>"). Requiring whitespace
    # right before it keeps prose intact, and immunises a COMPLETE tag, whose
    # suffixes are always preceded by '<' or '/'.
    for tag in _WRAPPER_TAGS:
        for k in range(len(tag) - 1, 4, -1):
            if not text.endswith(tag[-k:]):
                continue
            head = text[: len(text) - k]
            if head and not head[-1].isspace():
                continue
            return head
    return text


def _detect_fake_call(text: str) -> str | None:
    """Return the offending excerpt when text imitates a tool call/result."""
    lowered = text.lower()
    for marker in _FAKE_CALL_MARKERS:
        at = lowered.find(marker)
        if at != -1:
            return text[at:at + 500]
    for match in _FAKE_JSON_BLOCK_RE.finditer(text):
        block = match.group(0)
        if '"name"' in block and any(key in block for key in _FAKE_ARG_KEYS):
            return block[:500]
    return None


class XmlToolStreamParser:
    """Stateful, chunk-fed extractor of <tool_use> blocks from streamed text."""

    def __init__(self):
        self._buffer = ""
        # Partial <tool_calls>/</tool_calls> tag split across two chunks.
        self._wrapper_pending = ""
        # Visible text seen this turn (bounded) and whether a real call came out:
        # together they tell a tool-less turn from a hallucinated one.
        self._seen_text = ""
        self._emitted_any = False
        self._in_fenced_block = False
        self._in_inline_code = 0  # 0 = not in inline code; >0 = backtick count to match
        self._in_thinking = False
        self._in_tool_result = False
        # Human-readable note per malformation repaired at finalize() — a
        # recovery must stay observable, never silent.
        self.recovered_slips: list[str] = []
        # True once the batch wrapper closed AT TOP LEVEL — never from a mention
        # sitting inside a param body or a CDATA section. The stream backend
        # stops reading on this flag, which is what lets us drop the API stop
        # sequence: a turn is allowed to quote the protocol's own syntax.
        self.batch_closed = False
        # Last fed delta as the transcript must store it (see feed()).
        self.history_delta = ""
        # The model's raw text so far: a top-level close is only trusted after checking
        # it is WRITTEN (not in thinking, code or quotes) and follows an opening.
        self._raw = ""

    def feed(self, chunk: str) -> list[str | dict]:
        """Parse chunk, return interleaved list of visible text (str) and completed tools (dict)."""
        # The wrapper strip must see the buffered head of an unfinished tool_use:
        # judging the chunk alone would call a param body "top level" and erase a
        # wrapper tag the model deliberately quoted inside it.
        head = self._buffer
        _, call_open = _top_level_spans(head)
        if not self._wrapper_pending and not call_open:
            chunk = _drop_orphan_wrapper_suffix(chunk)
        # What the transcript should keep of this delta: the raw text minus an orphan
        # wrapper tail (otherwise the leftover resurfaces from the stored message).
        self.history_delta = chunk
        # Character written just before this text (the held tag head included).
        back = len(self._wrapper_pending) + 1
        before = self._raw[-back] if not head and len(self._raw) >= back else ""
        self._raw += chunk
        chunk, self._wrapper_pending, closed_at_top = _strip_wrapper_tags(
            head + self._wrapper_pending + chunk, offset=len(head), before=before
        )
        if closed_at_top and not self.batch_closed and _is_real_batch_close(self._raw):
            # Top-level close of the batch: the turn is over. The stream layer
            # reads this to hang up itself, instead of asking the API to stop on
            # a literal the model must stay free to quote inside a param.
            self.batch_closed = True
        items = self._feed_inner(chunk)
        self._note_items(items)
        return items

    def _note_items(self, items: list) -> None:
        for item in items:
            if isinstance(item, dict):
                if item.get("name") != "_XmlParseError":
                    self._emitted_any = True
            elif len(self._seen_text) < _SEEN_TEXT_LIMIT:
                self._seen_text += item

    def _feed_inner(self, chunk: str) -> list[str | dict]:
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
                hold_th = _max_prefix_suffix(self._buffer, "<thinking>")
                hold = max(hold_tu, hold_tr, hold_th)
                emit_to = len(self._buffer) - hold
                text = self._buffer[:emit_to]
                stripped = text.rstrip('\n')
                nl_hold = len(text) - len(stripped)
                if stripped:
                    result.append(stripped)
                self._buffer = self._buffer[emit_to - nl_hold:]
                # Track fenced/inline code state for next chunk
                # BUT exclude thinking content from code tracking
                tracking_text, enters_thinking = _text_for_code_tracking(stripped)
                if enters_thinking:
                    self._in_thinking = True
                elif _has_unclosed_fence(tracking_text):
                    self._in_fenced_block = True
                else:
                    bt = _has_unclosed_inline(tracking_text)
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
                # BUT exclude thinking content from code tracking
                tracking_text, enters_thinking = _text_for_code_tracking(stripped)
                if enters_thinking:
                    self._in_thinking = True
                elif _has_unclosed_fence(tracking_text):
                    self._in_fenced_block = True
                else:
                    bt = _has_unclosed_inline(tracking_text)
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
                # FIX: backticks inside a closed <thinking> region must not
                # prevent parsing of real tool_use tags outside that region.
                if _is_in_thinking(self._buffer, region_start) is not None:
                    code_info = None
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
            parsed = _parse_block(block)
            # None = the model was quoting the tag, not calling a tool: the block
            # goes back to the visible text it always was, with no tool call and
            # no error to answer.
            result.append(block if parsed is None else parsed)
            self._buffer = self._buffer.lstrip('\n')
        return result

    def finalize(self) -> list[dict]:
        """Flush the tail, then refuse to end a turn on a hallucinated tool call."""
        self._seen_text += self._buffer[:_SEEN_TEXT_LIMIT]
        # A pending wrapper fragment that never resolved is ordinary prose
        # (e.g. a turn ending on "3 <"): flush it as visible text, never drop it.
        pending = self._wrapper_pending
        self._wrapper_pending = ""
        tail = self._finalize_tail()
        if pending:
            tail = [pending, *tail]
        self._note_items(tail)
        if tail:
            return tail
        if not self._emitted_any:
            excerpt = _detect_fake_call(self._seen_text)
            if excerpt:
                _log.warning("xml: turn produced no tool call but imitates one")
                return [_make_error(_FAKE_FORMAT_ERROR, excerpt)]
        return []

    def _finalize_tail(self) -> list[dict]:
        leftover = self._buffer
        self._buffer = ""
        if self._in_fenced_block:
            return []
        if not leftover.lstrip().startswith(TOOL_OPEN_PREFIX):
            return []
        # Check if inside an inline code region
        stripped = leftover.lstrip()
        tool_pos = len(leftover) - len(stripped)
        if _is_in_code(leftover, tool_pos) is not None:
            return []
        # Same rule as _parse_block: a bare <tool_use> that never closed is the
        # model quoting the tag, not a truncated call — `name` is mandatory, so
        # there is nothing to re-emit and nothing to report.
        if _is_prose_mention(stripped):
            return []
        return self._recover_tail(stripped)

    def _recover_tail(self, text: str) -> list[dict]:
        """Salvage every well-formed tool call in an unparsable trailing buffer.

        A single malformed <param> used to invalidate the whole batch. Here the
        known malformations are repaired (see recovery.py), the repaired text is
        re-parsed, and only what is still broken becomes a _XmlParseError naming
        the tool and the param at fault.
        """
        repaired, notes = repair_tail(text)
        for note in notes:
            self.recovered_slips.append(note)
            _log.warning("XML tool-call auto-recovery: %s", note)
        replay = XmlToolStreamParser()
        recovered = [item for item in replay.feed(repaired) if isinstance(item, dict)]
        broken = replay._buffer if replay._buffer.strip() else ""
        if not broken and recovered:
            return recovered
        broken = broken or text
        diagnostic = describe_unclosed_tail(broken)
        if notes:
            diagnostic += f" (auto-recovered earlier in the same batch: {'; '.join(notes)})"
        recovered.append(_make_error(diagnostic, broken))
        return recovered
