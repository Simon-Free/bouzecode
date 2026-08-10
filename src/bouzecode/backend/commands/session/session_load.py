# [desc] CLI command to load saved chat sessions from disk with an interactive selection menu. [/desc]
"""Session loading command: load."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err

from bouzecode.backend.tools import ask_input_interactive
from ..info.info import cmd_history
from .session_pick import restore_state, format_session_label


def cmd_load(args: str, state, config) -> bool:
    from bouzecode.backend.core.config import SESSIONS_DIR, MR_SESSION_DIR, DAILY_DIR

    path = None
    arg = args.strip()

    date_str = None
    if not arg:
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
        date_str = arg

    if date_str is not None:
        day_dir = DAILY_DIR / date_str
        sessions: list[Path] = []
        if day_dir.exists():
            sessions = sorted(
                [s for s in day_dir.glob("session_*.json") if not s.name.endswith(".bak.json")],
                reverse=True,
            )

        if not sessions:
            info(f"No sessions found for {date_str}.")
            return True

        print(clr(f"  Sessions for {date_str}:", "cyan", "bold"))
        menu_buf = clr(f"  Sessions for {date_str}:", "cyan", "bold")
        prev_date = None
        for i, s in enumerate(sessions):
            date_label = s.parent.name if s.parent.name != "mr_sessions" else ""
            if date_label and date_label != prev_date:
                print(clr(f"\n  \u2500\u2500 {date_label} \u2500\u2500", "dim"))
                menu_buf += "\n" + clr(f"\n  \u2500\u2500 {date_label} \u2500\u2500", "dim")
                prev_date = date_label

            label = format_session_label(s)
            print(clr(f"  [{i+1:2d}] ", "yellow") + label)
            menu_buf += "\n" + clr(f"  [{i+1:2d}] ", "yellow") + label

        from bouzecode.backend.core.config import SESSION_HIST_FILE
        has_history = SESSION_HIST_FILE.exists()
        if has_history:
            try:
                hist_meta = json.loads(SESSION_HIST_FILE.read_text(encoding="utf-8"))
                n_sess = len(hist_meta.get("sessions", []))
                n_turns = hist_meta.get("total_turns", 0)
                print(clr("\n  \u2500\u2500 Complete History \u2500\u2500", "dim"))
                menu_buf += "\n" + clr("\n  \u2500\u2500 Complete History \u2500\u2500", "dim")
                hist_prt = clr("  [ H] ", "yellow") + f"Load ALL history  ({n_sess} sessions / {n_turns} total turns)  {SESSION_HIST_FILE}"
                print(hist_prt)
                menu_buf += "\n" + hist_prt
            except Exception:
                has_history = False

        print()
        ans = ask_input_interactive(clr("  Enter number(s) (e.g. 1 or 1,2,3), H for full history, or Enter to cancel > ", "cyan"), config, menu_buf).strip().lower()

        if not ans:
            info("  Cancelled.")
            return True

        if ans == "h":
            if not has_history:
                err("history.json not found.")
                return True
            hist_data = json.loads(SESSION_HIST_FILE.read_text(encoding="utf-8"))
            all_sessions = hist_data.get("sessions", [])
            if not all_sessions:
                info("history.json is empty.")
                return True
            all_messages = []
            for s in all_sessions:
                all_messages.extend(s.get("messages", []))
            total_turns = sum(s.get("turn_count", 0) for s in all_sessions)
            est_tokens = sum(len(str(m.get("content", ""))) for m in all_messages) // 4
            print()
            print(clr(f"  {len(all_messages)} messages / ~{est_tokens:,} tokens estimated", "dim"))
            confirm = ask_input_interactive(clr("  Load full history into current session? [y/N] > ", "yellow"), config).strip().lower()
            if confirm != "y":
                info("  Cancelled.")
                return True
            state.messages = all_messages
            state.turn_count = total_turns
            ok(f"Full history loaded from {SESSION_HIST_FILE} ({len(all_messages)} messages across {len(all_sessions)} sessions)")
            print()
            cmd_history("", state, config)
            return True

        raw_parts = [p.strip() for p in ans.split(",")]
        indices = []
        for p in raw_parts:
            if not p.isdigit():
                err(f"Invalid input '{p}'. Enter numbers separated by commas, or H.")
                return True
            idx = int(p) - 1
            if idx < 0 or idx >= len(sessions):
                err(f"Invalid selection: {p} (valid range: 1\u2013{len(sessions)})")
                return True
            if idx not in indices:
                indices.append(idx)

        if len(indices) == 1:
            path = sessions[indices[0]]
        else:
            all_messages = []
            total_turns = 0
            loaded_names = []
            for idx in indices:
                s_path = sessions[idx]
                s_data = json.loads(s_path.read_text(encoding="utf-8"))
                all_messages.extend(s_data.get("messages", []))
                total_turns += s_data.get("turn_count", 0)
                loaded_names.append(s_path.name)
            est_tokens = sum(len(str(m.get("content", ""))) for m in all_messages) // 4
            print()
            print(clr(f"  {len(loaded_names)} sessions / {len(all_messages)} messages / ~{est_tokens:,} tokens estimated", "dim"))
            confirm = ask_input_interactive(clr("  Merge and load? [y/N] > ", "yellow"), config).strip().lower()
            if confirm != "y":
                info("  Cancelled.")
                return True
            state.messages = all_messages
            state.turn_count = total_turns
            ok(f"Loaded {len(loaded_names)} sessions ({len(all_messages)} messages): {', '.join(loaded_names)}")
            print()
            cmd_history("", state, config)
            return True

    if not path:
        fname = arg
        path = Path(fname) if "/" in fname or "\\" in fname else SESSIONS_DIR / fname
        if not path.exists() and ("/" not in fname and "\\" not in fname):
            for alt in [MR_SESSION_DIR / fname,
                        *(d / fname for d in DAILY_DIR.iterdir()
                          if DAILY_DIR.exists() and d.is_dir())]:
                if alt.exists():
                    path = alt
                    break
        if not path.exists():
            err(f"File not found: {path}")
            return True

    data = json.loads(path.read_text(encoding="utf-8"))
    restore_state(state, data)
    ok(f"Session loaded from {path} ({len(state.messages)} messages)")
    print()
    cmd_history("", state, config)
    return True
