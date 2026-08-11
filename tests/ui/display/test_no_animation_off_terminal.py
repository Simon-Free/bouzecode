# [desc] The loading animation only runs on a real terminal, so `-p` output stays pipeable. [/desc]
"""`bouzecode -p "..." > out.txt` used to collect hundreds of spinner frames.

The spinner repaints every 100 ms with a leading `\\r`. A terminal overwrites
the line; a pipe keeps every frame, so one run produced 600+ lines of animation
around ~40 useful ones — unusable in a shell pipeline or a CI step, which is
exactly what `-p` ("run the prompt and exit") invites.
"""
from __future__ import annotations

import io
import sys
import time

from bouzecode.ui.spinner import (
    _start_tool_spinner,
    _stop_tool_spinner,
    animation_enabled,
)


class FakeTerminal(io.StringIO):
    """A stdout that claims to be a terminal."""

    def isatty(self):
        return True


def _spin_briefly(stream) -> tuple[bool, str]:
    """Run the spinner with `stream` as stdout; return (was enabled, what it wrote).

    The swap happens inside the test call, not in a fixture: pytest reinstalls
    its own capture object on sys.stdout between setup and call."""
    real_stdout = sys.stdout
    sys.stdout = stream
    try:
        enabled = animation_enabled()
        _start_tool_spinner()
        time.sleep(0.35)
        _stop_tool_spinner()
    finally:
        sys.stdout = real_stdout
    return enabled, stream.getvalue()


def test_a_pipe_receives_no_animation_frame():
    enabled, written = _spin_briefly(io.StringIO())

    assert enabled is False
    assert written == ""


def test_a_terminal_still_gets_its_spinner():
    enabled, written = _spin_briefly(FakeTerminal())

    assert enabled is True
    assert "\r" in written
