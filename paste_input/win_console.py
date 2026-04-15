# [desc] Windows console input reader using ReadConsoleInputW with bulk-drain support for large pastes. [/desc]
"""Windows console reader based on ReadConsoleInputW.

Disambiguates special keys (arrows, Home, End, Delete) from real Unicode
characters like 'a' (U+00E0), which msvcrt.getwch() confusingly returns
using the same \\xe0 prefix byte as arrow keys.

For large pastes (e.g. 150x150 chars), events are bulk-drained from the
console buffer to avoid the per-event syscall overhead that made big
pastes either slow or truncated.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes

_kernel32 = ctypes.windll.kernel32
_STD_INPUT_HANDLE = -10
_KEY_EVENT = 0x0001
_BULK_READ_SIZE = 512


class _KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("UnicodeChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", _KEY_EVENT_RECORD),
        ("_pad", ctypes.c_byte * 16),
    ]


class _INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wintypes.WORD),
        ("Event", _EVENT_UNION),
    ]


_VK_TO_CODE = {
    0x25: "K",  # VK_LEFT
    0x27: "M",  # VK_RIGHT
    0x26: "H",  # VK_UP
    0x28: "P",  # VK_DOWN
    0x24: "G",  # VK_HOME
    0x23: "O",  # VK_END
    0x2E: "S",  # VK_DELETE
}

# Pre-allocated bulk read buffer (reused across calls)
_bulk_buf = (_INPUT_RECORD * _BULK_READ_SIZE)()


def _stdin_handle():
    return _kernel32.GetStdHandle(_STD_INPUT_HANDLE)


def read_key() -> tuple[str | None, str | None]:
    """Block until a key-down event. Return (char, special).

    - Normal character: (char, None) -- char is a non-empty str of length 1.
    - Special key:      (None, code) -- code is one of K/M/H/P/G/O/S.
    """
    h = _stdin_handle()
    rec = _INPUT_RECORD()
    n = wintypes.DWORD()
    while True:
        if not _kernel32.ReadConsoleInputW(h, ctypes.byref(rec), 1, ctypes.byref(n)) or n.value == 0:
            continue
        if rec.EventType != _KEY_EVENT:
            continue
        ke = rec.Event.KeyEvent
        if not ke.bKeyDown:
            continue
        vk = ke.wVirtualKeyCode
        if vk in _VK_TO_CODE:
            return (None, _VK_TO_CODE[vk])
        ch = ke.UnicodeChar
        if ch and ch != "\x00":
            return (ch, None)


def drain_chars() -> list[str]:
    """Bulk-read all pending character key-down events from the console buffer.

    Reads up to _BULK_READ_SIZE events per syscall and extracts printable
    characters. Returns a (possibly empty) list of single-char strings.
    Much faster than calling read_key() in a loop for large pastes.
    """
    h = _stdin_handle()
    n_read = wintypes.DWORD()
    chars: list[str] = []
    while True:
        n_avail = wintypes.DWORD()
        if not _kernel32.GetNumberOfConsoleInputEvents(h, ctypes.byref(n_avail)) or n_avail.value == 0:
            break
        to_read = min(n_avail.value, _BULK_READ_SIZE)
        if not _kernel32.ReadConsoleInputW(h, _bulk_buf, to_read, ctypes.byref(n_read)):
            break
        found_any = False
        for i in range(n_read.value):
            rec = _bulk_buf[i]
            if rec.EventType != _KEY_EVENT:
                continue
            ke = rec.Event.KeyEvent
            if not ke.bKeyDown:
                continue
            if ke.wVirtualKeyCode in _VK_TO_CODE:
                continue  # ignore special keys inside paste
            ch = ke.UnicodeChar
            if ch and ch != "\x00":
                chars.append(ch)
                found_any = True
        if not found_any:
            break
    return chars


def keydown_pending() -> bool:
    """Non-blocking peek: True if a key-down event is queued."""
    h = _stdin_handle()
    n = wintypes.DWORD()
    if not _kernel32.GetNumberOfConsoleInputEvents(h, ctypes.byref(n)) or n.value == 0:
        return False
    peek_count = min(n.value, _BULK_READ_SIZE)
    read = wintypes.DWORD()
    if not _kernel32.PeekConsoleInputW(h, _bulk_buf, peek_count, ctypes.byref(read)):
        return False
    for i in range(read.value):
        if _bulk_buf[i].EventType == _KEY_EVENT and _bulk_buf[i].Event.KeyEvent.bKeyDown:
            ke = _bulk_buf[i].Event.KeyEvent
            if ke.wVirtualKeyCode in _VK_TO_CODE or (ke.UnicodeChar and ke.UnicodeChar != "\x00"):
                return True
    return False
