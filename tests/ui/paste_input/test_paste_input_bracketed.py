# [desc] Tests for bracketed paste -> badge collapsing + expansion on submit. [/desc]
"""Bracketed paste collapses into a single-line badge in the buffer, while the
real multi-line text is restored on submission via expand_paste_blocks().
"""
from __future__ import annotations

import threading
import time

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from bouzecode.ui import paste_input
from bouzecode.ui.paste_input import (
    _bindings,
    _pending,
    _BadgeProcessor,
    expand_paste_blocks,
)


def _piped_session(pipe_input) -> PromptSession:
    """A PromptSession wired to a pipe, with the real paste key bindings."""
    return PromptSession(
        input=pipe_input,
        output=DummyOutput(),
        history=InMemoryHistory(),
        multiline=False,
        key_bindings=_bindings,
        input_processors=[_BadgeProcessor()],
    )


def _run_with_piped_input(make_reader, input_text: str, timeout: float = 5.0):
    """Build a reader over a pipe input, run it in a thread, feed it input_text."""
    with create_pipe_input() as pipe_input:
        reader = make_reader(pipe_input)

        result = [None]
        exc = [None]

        def run():
            try:
                result[0] = reader()
            except (EOFError, KeyboardInterrupt) as e:
                exc[0] = e

        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.2)

        pipe_input.send_text(input_text)
        t.join(timeout=timeout)

    if exc[0]:
        raise exc[0]
    if t.is_alive():
        pytest.fail(f"reader did not return within {timeout}s")
    return result[0]


def _feed_and_read(input_text: str, timeout: float = 5.0) -> str:
    """Feed input_text into a fresh PromptSession and return the buffer result."""
    return _run_with_piped_input(
        lambda pipe_input: lambda: _piped_session(pipe_input).prompt(""),
        input_text,
        timeout,
    )


class TestBracketedPaste:
    """Verify multi-line paste collapses into a badge and expands on submit."""

    def test_multiline_paste_collapses_and_expands(self):
        """A multi-line paste becomes a single-line badge; expand restores it."""
        _pending.clear()
        paste_start = "\x1b[200~"
        paste_end = "\x1b[201~"
        pasted_text = "line1\nline2"

        buffer_result = _feed_and_read(f"{paste_start}{pasted_text}{paste_end}\r")

        # Buffer holds a single-line badge, not the raw newline.
        assert "\n" not in buffer_result
        assert "+2 lines" in buffer_result
        # The badge maps back to the full pasted text.
        assert expand_paste_blocks(buffer_result) == pasted_text

    def test_carriage_return_paste_collapses_and_expands(self):
        """Pastes using \\r line breaks (common on Windows terminals) still
        collapse into a badge and expand to \\n-separated text."""
        _pending.clear()
        buffer_result = _feed_and_read("\x1b[200~line1\rline2\rline3\x1b[201~\r")
        assert "\n" not in buffer_result
        assert "+3 lines" in buffer_result
        assert expand_paste_blocks(buffer_result) == "line1\nline2\nline3"

    def test_single_line_paste_inserted_verbatim(self):
        """A paste with no newline is inserted as-is (no badge)."""
        _pending.clear()
        buffer_result = _feed_and_read("\x1b[200~just one line\x1b[201~\r")
        assert buffer_result == "just one line"
        assert expand_paste_blocks(buffer_result) == "just one line"

    def test_normal_enter_submits_single_line(self):
        """A normal Enter (not inside bracketed paste) submits immediately."""
        _pending.clear()
        assert _feed_and_read("hello\r") == "hello"


class TestSecondaryPromptPaste:
    """Prompts raised outside the main REPL loop (AskUserQuestion choices,
    slash-command menus, permission prompts) get the same paste badges. They
    used to fall back to built-in input(), which submits a pasted block one
    line at a time -- each newline read as a separate answer."""

    def _read_answer(self, monkeypatch, input_text: str) -> str:
        from bouzecode.backend.tools.interaction import ask_input_interactive

        _pending.clear()
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        def make_reader(pipe_input):
            monkeypatch.setattr(
                paste_input, "_answer_session", _piped_session(pipe_input),
            )
            return lambda: ask_input_interactive("Your choice: ", {})

        return _run_with_piped_input(make_reader, input_text)

    def test_multiline_paste_answered_in_one_submission(self, monkeypatch):
        """A 4-line paste comes back whole, not as its first line."""
        pasted_text = "line1\nline2\nline3\nline4"
        answer = self._read_answer(
            monkeypatch, f"\x1b[200~{pasted_text}\x1b[201~\r",
        )
        assert answer == pasted_text

    def test_typed_answer_unchanged(self, monkeypatch):
        """Typing a plain choice still returns exactly what was typed."""
        assert self._read_answer(monkeypatch, "2\r") == "2"

    def test_answer_history_is_separate_from_repl_history(self, monkeypatch):
        """One-key answers do not land in the main REPL history."""
        paste_input._pt_history.append_string("previous repl input")
        self._read_answer(monkeypatch, "y\r")
        assert "y" not in paste_input._pt_history.get_strings()
