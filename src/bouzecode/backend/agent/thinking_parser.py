# [desc] Incremental streaming parser for <thinking> XML tags with repetitive-pattern loop detection. [/desc]
"""Incremental parser for <thinking> XML tags in text stream, with loop detection."""

import re


class ThinkingStreamParser:
    """Parses a stream of text chunks, separating <thinking>...</thinking> blocks from regular text."""

    OPEN_TAG = "<thinking>"
    CLOSE_TAG = "</thinking>"

    def __init__(self):
        self._buffer = ""
        self._in_thinking = False
        self._thinking_text: list[str] = []
        self._at_line_start = True  # start of stream = start of line

    def _is_at_line_start(self, idx: int) -> bool:
        if idx == 0:
            return self._at_line_start
        return self._buffer[idx - 1] == '\n'

    def _find_real(self, tag: str, *, streaming: bool = True, require_alone: bool = False) -> int:
        """Find tag at col 0.

        If *require_alone* is True the tag must be alone on its line
        (followed by ``\\n`` or at end-of-buffer in finalize mode).
        Use this for CLOSE_TAG to avoid false closes when content
        mentions ``</thinking>`` with trailing text on the same line.
        """
        search_start = 0
        while True:
            idx = self._buffer.find(tag, search_start)
            if idx == -1:
                return -1
            if self._is_at_line_start(idx):
                if not require_alone:
                    return idx  # col 0 is sufficient (open tag)
                end_pos = idx + len(tag)
                if end_pos >= len(self._buffer):
                    # Tag at very end of buffer — can't confirm alone on line
                    if not streaming:
                        return idx  # finalize: accept
                    return -1  # streaming: wait for more data
                if self._buffer[end_pos] == '\n':
                    return idx
                # Tag has trailing text — not a real structural tag
            search_start = idx + 1

    def _partial_retain(self, tag: str, *, require_alone: bool = False) -> int:
        """How many trailing chars to retain because they could become a real tag at line start.

        When *require_alone* is True, also retains a FULL tag at end of
        buffer if it's at col 0 but we can't yet confirm it's alone on
        line (no ``\\n`` seen after it).
        """
        # Full tag at end of buffer at col 0 — can't confirm alone on line yet
        if require_alone and len(self._buffer) >= len(tag):
            pos = len(self._buffer) - len(tag)
            if self._buffer[pos:] == tag and self._is_at_line_start(pos):
                return len(tag)
        # Partial prefix at end of buffer at col 0
        for i in range(min(len(tag) - 1, len(self._buffer)), 0, -1):
            suffix = self._buffer[-i:]
            if tag[:i] == suffix:
                pos = len(self._buffer) - i
                if self._is_at_line_start(pos):
                    return i
        return 0

    def _update_line_start(self, consumed: str):
        if consumed:
            self._at_line_start = consumed[-1] == '\n'

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """Feed a chunk. Returns list of ("text", content) or ("thinking", content) tuples."""
        self._buffer += chunk
        results: list[tuple[str, str]] = []

        while self._buffer:
            if self._in_thinking:
                end_idx = self._find_real(self.CLOSE_TAG, require_alone=True)
                if end_idx != -1:
                    thinking_content = self._buffer[:end_idx]
                    if thinking_content:
                        results.append(("thinking", thinking_content))
                        self._thinking_text.append(thinking_content)
                    self._update_line_start(self._buffer[:end_idx + len(self.CLOSE_TAG)])
                    self._buffer = self._buffer[end_idx + len(self.CLOSE_TAG):]
                    self._in_thinking = False
                else:
                    retain = self._partial_retain(self.CLOSE_TAG, require_alone=True)
                    if retain:
                        emit = self._buffer[:-retain]
                        if emit:
                            results.append(("thinking", emit))
                            self._thinking_text.append(emit)
                            self._update_line_start(emit)
                        self._buffer = self._buffer[-retain:]
                    else:
                        results.append(("thinking", self._buffer))
                        self._thinking_text.append(self._buffer)
                        self._update_line_start(self._buffer)
                        self._buffer = ""
                    break
            else:
                start_idx = self._find_real(self.OPEN_TAG)
                if start_idx != -1:
                    text_before = self._buffer[:start_idx]
                    if text_before:
                        results.append(("text", text_before))
                    self._update_line_start(self._buffer[:start_idx + len(self.OPEN_TAG)])
                    self._buffer = self._buffer[start_idx + len(self.OPEN_TAG):]
                    self._in_thinking = True
                else:
                    retain = self._partial_retain(self.OPEN_TAG)
                    if retain:
                        emit = self._buffer[:-retain]
                        if emit:
                            results.append(("text", emit))
                            self._update_line_start(emit)
                        self._buffer = self._buffer[-retain:]
                    else:
                        results.append(("text", self._buffer))
                        self._update_line_start(self._buffer)
                        self._buffer = ""
                    break

        return results

    def finalize(self) -> list[tuple[str, str]]:
        """Flush remaining buffer, accepting tags at end of buffer."""
        results: list[tuple[str, str]] = []
        while self._buffer:
            if self._in_thinking:
                end_idx = self._find_real(self.CLOSE_TAG, streaming=False, require_alone=True)
                if end_idx != -1:
                    thinking_content = self._buffer[:end_idx]
                    if thinking_content:
                        results.append(("thinking", thinking_content))
                        self._thinking_text.append(thinking_content)
                    self._update_line_start(
                        self._buffer[:end_idx + len(self.CLOSE_TAG)])
                    self._buffer = self._buffer[end_idx + len(self.CLOSE_TAG):]
                    self._in_thinking = False
                else:
                    results.append(("thinking", self._buffer))
                    self._thinking_text.append(self._buffer)
                    self._buffer = ""
            else:
                start_idx = self._find_real(self.OPEN_TAG, streaming=False)
                if start_idx != -1:
                    text_before = self._buffer[:start_idx]
                    if text_before:
                        results.append(("text", text_before))
                    self._update_line_start(
                        self._buffer[:start_idx + len(self.OPEN_TAG)])
                    self._buffer = self._buffer[start_idx + len(self.OPEN_TAG):]
                    self._in_thinking = True
                else:
                    results.append(("text", self._buffer))
                    self._buffer = ""
        return results

    @property
    def full_thinking_text(self) -> str:
        return "".join(self._thinking_text)

    @property
    def in_thinking(self) -> bool:
        return self._in_thinking


class LoopDetector:
    """Detects repetitive patterns in a stream of text."""

    WINDOW_SIZE = 2000
    PATTERN_LENGTHS = list(range(20, 51)) + list(range(55, 201, 5))
    MIN_REPEATS = 8

    def __init__(self):
        self._window = ""

    def feed(self, text: str) -> bool:
        """Feed text. Returns True if a loop is detected."""
        self._window += text
        if len(self._window) > self.WINDOW_SIZE:
            self._window = self._window[-self.WINDOW_SIZE:]
        if len(self._window) < 200:
            return False
        return any(self._check_pattern(plen) for plen in self.PATTERN_LENGTHS)

    def _check_pattern(self, pattern_length: int) -> bool:
        needed = pattern_length * self.MIN_REPEATS
        if len(self._window) < needed:
            return False
        tail = self._window[-needed:]
        pattern = tail[:pattern_length]
        return all(
            tail[i : i + pattern_length] == pattern
            for i in range(pattern_length, needed, pattern_length)
        )


class ThinkingDisciplineMonitor:
    """Analyze completed thinking blocks for discipline violations."""

    DIRECTION_CHANGE_RE = re.compile(
        r'\b(?:wait|attendons?|attends|actually|hmm+|'
        r'non en fait|no wait|let me (?:re)?think|reconsider)\b',
        re.IGNORECASE,
    )
    STOP_RE = re.compile(
        r'\b(?:ok\s+stop|enough\s+thinking|je\s+over-?engineer)\b',
        re.IGNORECASE,
    )
    MAX_DIRECTION_CHANGES = 2
    MAX_LINES = 100

    def analyze(self, text: str) -> list[dict]:
        lines = text.splitlines()
        violations: list[dict] = []

        # Direction changes
        changes = self.DIRECTION_CHANGE_RE.findall(text)
        if len(changes) > self.MAX_DIRECTION_CHANGES:
            violations.append({
                "type": "direction_changes",
                "detail": f"{len(changes)} direction changes (max {self.MAX_DIRECTION_CHANGES})",
                "count": len(changes),
            })

        # Continued after STOP
        for i, line in enumerate(lines):
            if self.STOP_RE.search(line):
                remaining = [ln for ln in lines[i + 1:] if ln.strip()]
                if len(remaining) > 5:
                    violations.append({
                        "type": "continued_after_stop",
                        "detail": f"{len(remaining)} non-empty lines after STOP at line {i + 1}",
                        "lines_after_stop": len(remaining),
                    })
                break

        # Line cap
        if len(lines) > self.MAX_LINES:
            violations.append({
                "type": "line_cap_exceeded",
                "detail": f"{len(lines)} lines (max {self.MAX_LINES})",
                "line_count": len(lines),
            })

        return violations


_THINKING_BLOCK_RE = re.compile(
    r'^<thinking>[ \t]*\n.*?^</thinking>[ \t]*$|<thinking>[^\n]*?</thinking>',
    re.DOTALL | re.MULTILINE,
)


def strip_tool_use_xml(content: str) -> str:
    """Remove <tool_use ...>...</tool_use> blocks from content.

    Uses XmlToolStreamParser to correctly handle CDATA sections
    (won't be confused by </tool_use> inside CDATA).
    Returns only the visible prose text.
    """
    if "<tool_use" not in content:
        return content.strip()
    from ..xml_tool_protocol.parser import XmlToolStreamParser
    parser = XmlToolStreamParser()
    items = parser.feed(content)
    parser.finalize()
    visible = "".join(item for item in items if isinstance(item, str))
    return visible.strip()


def strip_thinking_tags(content: str) -> str:
    """Remove <thinking>...</thinking> blocks (inline AND multiline).

    Two-pass: line-level drops "structural" blocks (lines that are exactly
    `<thinking>` / `</thinking>`) so a `</thinking>` mentioned inside thinking
    is not mistaken for the real close. Then a DOTALL regex handles inline
    blocks that share lines with surrounding text. Unclosed opens (Ctrl+C)
    drop everything from the unmatched `<thinking>` to the end.
    """
    if "<thinking>" not in content:
        return content.strip()
    kept_lines: list[str] = []
    in_structural_block = False
    for line in content.split('\n'):
        stripped_line = line.strip()
        if in_structural_block:
            # Only a </thinking> at column 0 (no leading whitespace) closes the block
            if stripped_line == '</thinking>' and not line[0:1].isspace():
                in_structural_block = False
            continue
        # Only a <thinking> at column 0 (no leading whitespace) opens a block
        if stripped_line == '<thinking>' and not line[0:1].isspace():
            in_structural_block = True
            continue
        kept_lines.append(line)
    cleaned = _THINKING_BLOCK_RE.sub("", '\n'.join(kept_lines))
    unclosed = re.search(r'^<thinking>', cleaned, re.MULTILINE)
    if unclosed:
        cleaned = cleaned[:unclosed.start()]
    return cleaned.strip()
