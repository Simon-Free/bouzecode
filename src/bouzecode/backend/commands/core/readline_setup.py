# [desc] Configures readline with persistent history, slash-command tab completion, and match display. [/desc]
"""Readline history + tab-completion for slash commands."""
from __future__ import annotations

import atexit
import sys
from pathlib import Path

try:
    import readline
except ImportError:
    readline = None

from ..dispatcher import _CMD_META


def setup_readline(history_file: Path) -> None:
    if readline is None:
        return
    try:
        readline.read_history_file(str(history_file))
    except (FileNotFoundError, OSError):
        # macOS libedit raises PermissionError on GNU-readline-format files.
        pass
    readline.set_history_length(1000)
    atexit.register(readline.write_history_file, str(history_file))

    delims = readline.get_completer_delims().replace("/", "")
    readline.set_completer_delims(delims)

    def completer(text: str, state: int):
        line = readline.get_line_buffer()
        if "/" in line and " " not in line:
            matches = sorted(f"/{c}" for c in _CMD_META if f"/{c}".startswith(text))
            return matches[state] if state < len(matches) else None
        if line.startswith("/") and " " in line:
            cmd = line.split()[0][1:]
            if cmd in _CMD_META:
                subs = _CMD_META[cmd][1]
                matches = sorted(s for s in subs if s.startswith(text))
                return matches[state] if state < len(matches) else None
        return None

    def display_matches(substitution: str, matches: list, longest: int):
        sys.stdout.write("\n")
        line = readline.get_line_buffer()
        is_cmd = "/" in line and " " not in line
        if is_cmd:
            col_w = max(len(m) for m in matches) + 2
            for m in sorted(matches):
                cmd = m[1:]
                desc = _CMD_META.get(cmd, ("", []))[0]
                subs = _CMD_META.get(cmd, ("", []))[1]
                sub_hint = ("  [" + ", ".join(subs[:4])
                            + ("\u2026" if len(subs) > 4 else "") + "]") if subs else ""
                sys.stdout.write(f"  \033[36m{m:<{col_w}}\033[0m  {desc}{sub_hint}\n")
        else:
            for m in sorted(matches):
                sys.stdout.write(f"  {m}\n")
        sys.stdout.flush()

    readline.set_completion_display_matches_hook(display_matches)
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
