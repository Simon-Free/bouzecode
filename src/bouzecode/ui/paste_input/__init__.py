# [desc] Package entry point: prompt_toolkit input with collapsible paste badges. [/desc]
"""Multi-line input powered by prompt_toolkit, with collapsible paste badges.

- Enter submits. Alt+Enter inserts a newline for multi-line editing.
- A multi-line paste (>= PASTE_BADGE_THRESHOLD lines) collapses into a single
  dimmed badge ``[line1 (+42 lines)]`` in the buffer. The real text is kept in a
  registry and expanded back on submission, so the agent receives the full paste.
- Backspace right after a badge removes the whole badge atomically.
- History is shared across the session.
"""
from __future__ import annotations

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI, fragment_list_to_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.styles import Style

from .segments import paste_badge_label

PASTE_BADGE_THRESHOLD = 2

_history_list: list[str] = []
_MAX_HISTORY = 200

_pt_history = InMemoryHistory()
_session: PromptSession | None = None

# Maps the single-line placeholder shown in the buffer -> the real pasted text.
# Reset at the start of every read; consumed when the input is submitted.
_pending: dict[str, str] = {}
_paste_counter = 0

_bindings = KeyBindings()

_style = Style.from_dict({"paste-badge": "fg:ansicyan italic"})


@_bindings.add("escape", "enter")
def _insert_newline(event):
    """Alt+Enter inserts a newline."""
    event.current_buffer.insert_text("\n")


@_bindings.add(Keys.BracketedPaste)
def _on_paste(event):
    """Collapse a multi-line paste into a badge; insert short pastes verbatim.

    Terminals may deliver paste line breaks as ``\\r``, ``\\r\\n`` or ``\\n``;
    normalize to ``\\n`` so multi-line detection and the expanded text are clean.
    """
    data = event.data.replace("\r\n", "\n").replace("\r", "\n")
    if data.count("\n") + 1 >= PASTE_BADGE_THRESHOLD:
        global _paste_counter
        _paste_counter += 1
        placeholder = f"[#{_paste_counter} {paste_badge_label(data)}]"
        _pending[placeholder] = data
        event.current_buffer.insert_text(placeholder)
    else:
        event.current_buffer.insert_text(data)


@_bindings.add("backspace")
def _backspace(event):
    """Delete a whole paste badge atomically when the cursor sits right after it."""
    buf = event.current_buffer
    before = buf.document.text_before_cursor
    for placeholder in _pending:
        if before.endswith(placeholder):
            buf.delete_before_cursor(len(placeholder))
            _pending.pop(placeholder, None)
            return
    buf.delete_before_cursor(1)


class _BadgeProcessor(Processor):
    """Style any paste-badge placeholders in the buffer with the dim badge style."""

    def apply_transformation(self, ti):
        if not _pending:
            return Transformation(ti.fragments)
        text = fragment_list_to_text(ti.fragments)
        spans = []
        for placeholder in _pending:
            start = 0
            while (i := text.find(placeholder, start)) >= 0:
                spans.append((i, i + len(placeholder)))
                start = i + len(placeholder)
        if not spans:
            return Transformation(ti.fragments)
        spans.sort()
        fragments = []
        pos = 0
        for start, end in spans:
            if start < pos:
                continue
            if start > pos:
                fragments.append(("", text[pos:start]))
            fragments.append(("class:paste-badge", text[start:end]))
            pos = end
        if pos < len(text):
            fragments.append(("", text[pos:]))
        return Transformation(fragments)


def _get_session() -> PromptSession:
    global _session
    if _session is None:
        _session = PromptSession(
            history=_pt_history,
            multiline=False,
            key_bindings=_bindings,
            input_processors=[_BadgeProcessor()],
            style=_style,
        )
    return _session


def add_history(text: str):
    if text.strip() and (not _history_list or _history_list[-1] != text):
        _history_list.append(text)
        if len(_history_list) > _MAX_HISTORY:
            _history_list.pop(0)
        _pt_history.append_string(text)


def get_history() -> list[str]:
    return _history_list


def expand_paste_blocks(text: str) -> str:
    """Replace badge placeholders with their original pasted text."""
    for placeholder, full_text in _pending.items():
        text = text.replace(placeholder, full_text)
    return text


def read_input_with_paste_blocks(prompt: str) -> str:
    """Read input with multi-line support and collapsible paste badges.

    - Enter submits, Alt+Enter inserts a newline.
    - Multi-line pastes collapse into a badge, expanded back on submission.

    Returns the full text (badges expanded) ready for submission.
    """
    if not sys.stdin.isatty():
        return input(prompt)

    _pending.clear()
    session = _get_session()
    result = session.prompt(ANSI(prompt))
    return expand_paste_blocks(result)
