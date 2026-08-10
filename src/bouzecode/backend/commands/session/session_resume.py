# [desc] CLI /resume command: interactive picker over the most recent saved sessions, with paging to older ones. [/desc]
"""Session resume command: propose the latest sessions, pick one, load more on demand."""
from __future__ import annotations

import json
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr, info, ok, err
except ImportError:
    from bouzecode import clr, info, ok, err

from bouzecode.backend.tools import ask_input_interactive
from ..info.info import cmd_history
from .session_pick import restore_state, format_session_label, collect_recent_sessions

_PAGE = 10


def _load_into(state, config, path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    restore_state(state, data)
    ok(f"Session loaded from {path} ({len(state.messages)} messages)")
    print()
    cmd_history("", state, config)


def _render_menu(sessions: list[Path], shown: int) -> str:
    lines = [clr("  Recent sessions:", "cyan", "bold")]
    for i, s in enumerate(sessions[:shown]):
        lines.append(clr(f"  [{i + 1:2d}] ", "yellow") + format_session_label(s, with_date=True))
    body = "\n".join(lines)
    print(body)
    return body


def cmd_resume(args: str, state, config) -> bool:
    """No arg: interactive picker. With a file/path arg: load it directly (legacy)."""
    if args.strip():
        return _resume_explicit(args.strip(), state, config)

    sessions = collect_recent_sessions()
    if not sessions:
        info("No saved sessions found.")
        return True

    shown = min(_PAGE, len(sessions))
    while True:
        menu_buf = _render_menu(sessions, shown)
        more = len(sessions) > shown
        hint = "number to resume"
        if more:
            hint += ", m for more"
        print()
        ans = ask_input_interactive(
            clr(f"  Enter {hint}, or Enter to cancel > ", "cyan"), config, menu_buf
        ).strip().lower()

        if not ans:
            info("  Cancelled.")
            return True
        if ans == "m" and more:
            shown = min(shown + _PAGE, len(sessions))
            print()
            continue
        if not ans.isdigit():
            err(f"Invalid input '{ans}'. Enter a number" + (", m for more," if more else "") + " or Enter to cancel.")
            return True
        idx = int(ans) - 1
        if idx < 0 or idx >= shown:
            err(f"Invalid selection: {ans} (valid range: 1–{shown})")
            return True
        _load_into(state, config, sessions[idx])
        return True


def _resume_explicit(fname: str, state, config) -> bool:
    from bouzecode.backend.core.config import MR_SESSION_DIR

    path = Path(fname) if ("/" in fname or "\\" in fname) else MR_SESSION_DIR / fname
    if not path.exists():
        err(f"File not found: {path}")
        return True
    _load_into(state, config, path)
    return True
