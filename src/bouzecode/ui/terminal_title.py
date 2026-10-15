"""Terminal tab title reflecting the agent status (OSC 0 escape sequence).

Statuses:
    running  -> loader while bouzecode works
    done     -> check mark after a FinalAnswer
    crashed  -> cross after a crash
    question -> question mark while an AskUserQuestion waits for the user
    idle     -> plain title
"""
from __future__ import annotations

import os
import sys

_BASE_TITLE = "bouzecode"

STATUS_ICONS = {
    "running": "\u23f3",   # hourglass
    "done": "\u2705",      # check mark
    "crashed": "\u274c",   # cross
    "question": "\u2753",  # question mark
    "idle": "",
}

_current_status: str | None = None


def build_title(status: str, base: str | None = None) -> str:
    """Return the title text for *status* (unknown status -> plain title)."""
    base = base or _base_title()
    icon = STATUS_ICONS.get(status, "")
    return f"{icon} {base}" if icon else base


def title_sequence(status: str, base: str | None = None) -> str:
    """OSC 0 escape sequence setting the tab/window title."""
    return f"\x1b]0;{build_title(status, base)}\x07"


def _base_title() -> str:
    try:
        folder = os.path.basename(os.getcwd())
    except OSError:
        folder = ""
    return f"{_BASE_TITLE} - {folder}" if folder else _BASE_TITLE


_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_vt_handles: set[int] = set()


def _enable_vt(stream) -> bool:
    """Best-effort: enable VT processing on a Windows console *stream*.

    A legacy conhost console silently ignores OSC sequences unless
    ENABLE_VIRTUAL_TERMINAL_PROCESSING is set (prompt_toolkit only sets it
    while the prompt is displayed). Returns True when VT is (now) enabled.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return False
    if handle in _vt_handles:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        mode = ctypes.c_uint32()
        h = ctypes.c_void_p(handle)
        if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        if not mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            if not kernel32.SetConsoleMode(
                h, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
            ):
                return False
    except (AttributeError, OSError):
        return False
    _vt_handles.add(handle)
    return True


def set_terminal_status(status: str, stream=None) -> bool:
    """Write the title for *status* to the terminal.

    No-op (returns False) when the stream is not a TTY (pipes, web agents, CI)
    or when BOUZECODE_NO_TERMINAL_TITLE is set.
    """
    global _current_status
    stream = stream if stream is not None else sys.stdout
    if os.environ.get("BOUZECODE_NO_TERMINAL_TITLE"):
        return False
    try:
        if not stream.isatty():
            return False
        _enable_vt(stream)
        stream.write(title_sequence(status))
        stream.flush()
    except (AttributeError, OSError, ValueError):
        return False
    _current_status = status
    return True


def current_status() -> str | None:
    return _current_status
