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

    @property
    def in_thinking(self) -> bool:
        """True while the parser is currently inside an unclosed <thinking> block."""
        return self._in_thinking

    def pending_body(self) -> str:
        """Buffered body text not yet emitted (e.g. a partial <tool_use> tag).

        Returns the retained buffer ONLY when NOT inside a thinking block, so
        partial thinking content is never leaked into the assistant body.
        """
        return "" if self._in_thinking else self._buffer

    def _is_at_line_start(self, idx: int) -> bool:
        if idx == 0:
            return self._at_line_start
        return self._buffer[idx - 1] == '\n'

    def _find_real(self, tag: str, *, streaming: bool = True, require_alone: bool = False) -> int:
        """Find tag at col 0.

        Column 0 is what makes a tag structural — for BOTH tags. A model that
        writes ``</thinking> and now the answer`` still means to close, so the
        tag is accepted and the rest of the line is emitted as plain text by
        the caller. Protection against a literal *mention* of ``</thinking>``
        inside content is kept by :meth:`_is_at_line_start`: a mention appears
        mid-line or inside an indented code block, never at column 0.

        *require_alone* / *streaming* are kept for the buffer-retention path
        (:meth:`_partial_retain`); they no longer reject trailing text.
        """
        search_start = 0
        while True:
            idx = self._buffer.find(tag, search_start)
            if idx == -1:
                return -1
            if self._is_at_line_start(idx):
                return idx  # col 0 is sufficient (open AND close tag)
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
                close_idx = self._find_real(self.CLOSE_TAG)
                if close_idx != -1 and (start_idx == -1 or close_idx < start_idx):
                    # Orphan close tag: the open tag was lost, so everything
                    # before it was the reflection. Consume the tag (never
                    # render it) and stay outside thinking afterwards.
                    orphan_thinking = self._buffer[:close_idx]
                    if orphan_thinking:
                        results.append(("thinking", orphan_thinking))
                        self._thinking_text.append(orphan_thinking)
                    self._update_line_start(self._buffer[:close_idx + len(self.CLOSE_TAG)])
                    self._buffer = self._buffer[close_idx + len(self.CLOSE_TAG):]
                    continue
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
    # NOTE: a STREAM parser must never be used for this one-shot cleanup.
    # XmlToolStreamParser retains its buffer on an unpaired opening tag and
    # finalize() throws that buffer away, so a tool tag merely MENTIONED in
    # the prose used to swallow the whole message (observed: assistant
    # messages persisted as "." or as a 10-char residue). Bounded textual
    # removal instead: only a properly PAIRED block is removed, anything
    # unpaired stays as plain text.
    tool_open = "<" + "tool_use"
    tool_close = "</" + "tool_use" + ">"
    cdata_open = "<![" + "CDATA["
    cdata_close = "]]" + ">"
    batch_open = "<" + "tool_calls" + ">"
    batch_close = "</" + "tool_calls" + ">"

    def _paired_close(text: str, start: int) -> int:
        """Index just after the tool_use close matching the open at `start`.

        Skips CDATA sections so a close tag quoted inside CDATA is ignored.
        Returns -1 when no matching close exists.
        """
        i = start
        while i < len(text):
            cd = text.find(cdata_open, i)
            end = text.find(tool_close, i)
            if end == -1:
                return -1
            if cd != -1 and cd < end:
                cd_end = text.find(cdata_close, cd + len(cdata_open))
                if cd_end == -1:
                    return -1
                i = cd_end + len(cdata_close)
                continue
            return end + len(tool_close)
        return -1

    kept: list[str] = []
    pos = 0
    while pos < len(content):
        found = content.find(tool_open, pos)
        if found == -1:
            kept.append(content[pos:])
            break
        after = content[found + len(tool_open):found + len(tool_open) + 1]
        if after not in (" ", "\t", "\n", "\r", ">"):
            # e.g. "<tool_useless": not a tool tag, plain text
            kept.append(content[pos:found + len(tool_open)])
            pos = found + len(tool_open)
            continue
        line_start = content.rfind("\n", 0, found) + 1
        if content[line_start:found].strip():
            # Inline mention inside prose (a real tool block always starts its
            # own line). Keep it verbatim and keep scanning after it, so a real
            # block further down is still removed.
            kept.append(content[pos:found + len(tool_open)])
            pos = found + len(tool_open)
            continue
        close_at = _paired_close(content, found)
        if close_at == -1:
            # Unpaired open tag: prose mention, keep everything verbatim.
            kept.append(content[pos:])
            break
        kept.append(content[pos:found])
        pos = close_at

    visible = "".join(kept)
    lines = [
        line for line in visible.split("\n")
        if line.strip() not in (batch_open, batch_close)
    ]
    return "\n".join(lines).strip()


def normalize_orphan_close_tags(content: str) -> str:
    """Make an orphan ``</thinking>`` well-formed by inserting the missing open tag.

    A ``</thinking>`` at column 0 with no block currently open means the model
    lost / forgot its opening tag: everything since the start of the current
    segment WAS the reflection. We insert a ``<thinking>`` line at the start of
    that segment, so every downstream regex/parser sees a well-formed block
    instead of leaking the raw tag into the visible prose.

    Trailing text on the close-tag line is moved to its own line so the
    line-level (structural) passes see a lone ``</thinking>`` and still close
    the block — otherwise everything after it would be swallowed.

    Only column 0 is structural: an indented or mid-line *mention* of either
    tag is left untouched.
    """
    open_tag = ThinkingStreamParser.OPEN_TAG
    close_tag = ThinkingStreamParser.CLOSE_TAG
    if close_tag not in content:
        return content
    out: list[str] = []
    segment_start = 0  # index in `out` where the current unopened segment begins
    is_open = False
    for line in content.split('\n'):
        if line.startswith(open_tag):
            # An inline block (open AND close on the same line) is self-contained.
            if close_tag not in line[len(open_tag):]:
                is_open = True
            out.append(line)
            continue
        if line.startswith(close_tag):
            trailing = line[len(close_tag):]
            if not is_open:
                out.insert(segment_start, open_tag)
            is_open = False
            out.append(close_tag)
            if trailing.strip():
                out.append(trailing.lstrip())
            segment_start = len(out)
            continue
        out.append(line)
    return '\n'.join(out)


def strip_thinking_tags(content: str) -> str:
    """Remove <thinking>...</thinking> blocks (inline AND multiline).

    Two-pass: line-level drops "structural" blocks (lines that are exactly
    `<thinking>` / `</thinking>`) so a `</thinking>` mentioned inside thinking
    is not mistaken for the real close. Then a DOTALL regex handles inline
    blocks that share lines with surrounding text. Unclosed opens (Ctrl+C)
    drop everything from the unmatched `<thinking>` to the end.
    """
    content = normalize_orphan_close_tags(content)
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
