# [desc] CLI commands to load and resume saved chat sessions from disk with interactive selection menu. [/desc]
"""Session loading commands: load, resume."""
from __future__ import annotations

import json
from pathlib import Path

try:
    from ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err

from tools import ask_input_interactive
from commands.info import cmd_history


def _restore_state(state, data: dict) -> None:
    state.messages = data.get("messages", [])
    state.turn_count = data.get("turn_count", 0)
    state.total_input_tokens = data.get("total_input_tokens", 0)
    state.total_output_tokens = data.get("total_output_tokens", 0)
    state.total_cache_read_tokens = data.get("total_cache_read_tokens", 0)
    state.total_cache_creation_tokens = data.get("total_cache_creation_tokens", 0)
    state.distinct_base = data.get("distinct_base", 0)


def cmd_load(args: str, state, config) -> bool:
    from config import SESSIONS_DIR, MR_SESSION_DIR, DAILY_DIR

    path = None
    if not args.strip():
        sessions: list[Path] = []
        if DAILY_DIR.exists():
            for day_dir in sorted(DAILY_DIR.iterdir(), reverse=True):
                if day_dir.is_dir():
                    sessions.extend(sorted(day_dir.glob("session_*.json"), reverse=True))
        if not sessions and MR_SESSION_DIR.exists():
            sessions = [s for s in sorted(MR_SESSION_DIR.glob("*.json"), reverse=True)
                        if s.name != "session_latest.json"]
        sessions.extend(sorted(SESSIONS_DIR.glob("session_*.json"), reverse=True))

        if not sessions:
            info("No saved sessions found.")
            return True

        print(clr("  Select a session to load:", "cyan", "bold"))
        menu_buf = clr("  Select a session to load:", "cyan", "bold")
        prev_date = None
        for i, s in enumerate(sessions):
            date_label = s.parent.name if s.parent.name != "mr_sessions" else ""
            if date_label and date_label != prev_date:
                print(clr(f"\n  \u2500\u2500 {date_label} \u2500\u2500", "dim"))
                menu_buf += "\n" + clr(f"\n  \u2500\u2500 {date_label} \u2500\u2500", "dim")
                prev_date = date_label

            label = s.name
            try:
                meta = json.loads(s.read_text())
                saved_at = meta.get("saved_at", "")[-8:]
                sid = meta.get("session_id", "")
                turns = meta.get("turn_count", "?")
                preview = meta.get("first_message", "")
                if not preview:
                    for msg in meta.get("messages", []):
                        if msg.get("role") == "user":
                            c = msg.get("content", "")
                            if isinstance(c, list):
                                c = next((b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"), "")
                            if c:
                                preview = c.replace("\n", " ").strip()[:80]
                                break
                label = f"{saved_at}  id:{sid}  turns:{turns}"
                if preview:
                    label += f'  "{preview}"'
            except Exception:
                pass
            print(clr(f"  [{i+1:2d}] ", "yellow") + label)
            menu_buf += "\n" + clr(f"  [{i+1:2d}] ", "yellow") + label

        from config import SESSION_HIST_FILE
        has_history = SESSION_HIST_FILE.exists()
        if has_history:
            try:
                hist_meta = json.loads(SESSION_HIST_FILE.read_text())
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
            hist_data = json.loads(SESSION_HIST_FILE.read_text())
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
                s_data = json.loads(s_path.read_text())
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
        fname = args.strip()
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

    data = json.loads(path.read_text())
    _restore_state(state, data)
    ok(f"Session loaded from {path} ({len(state.messages)} messages)")
    print()
    cmd_history("", state, config)
    return True


def cmd_resume(args: str, state, config) -> bool:
    from config import MR_SESSION_DIR

    if not args.strip():
        path = MR_SESSION_DIR / "session_latest.json"
        if not path.exists():
            info("No auto-saved sessions found.")
            return True
    else:
        fname = args.strip()
        path = Path(fname) if "/" in fname else MR_SESSION_DIR / fname

    if not path.exists():
        err(f"File not found: {path}")
        return True

    data = json.loads(path.read_text())
    _restore_state(state, data)
    ok(f"Session loaded from {path} ({len(state.messages)} messages)")
    print()
    cmd_history("", state, config)
    return True
