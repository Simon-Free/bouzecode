# [desc] Implements /checkpoint command for listing, restoring, and clearing conversation/file checkpoints. [/desc]
"""/checkpoint and /rewind commands."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

try:
    from ui.ansi import clr, ok, warn, err, info
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
         "red": "\033[31m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def info(msg):  print(clr(msg, "cyan"))
    def ok(msg):    print(clr(msg, "green"))
    def warn(msg):  print(clr(f"Warning: {msg}", "yellow"))
    def err(msg):   print(clr(f"Error: {msg}", "red"), file=sys.stderr)

from tools import ask_input_interactive


def cmd_checkpoint(args: str, state, config) -> bool:
    """List or restore checkpoints.

    /checkpoint          -- list all checkpoints
    /checkpoint <id>     -- restore to checkpoint #id
    /checkpoint clear    -- delete all checkpoints for this session
    """
    import checkpoint as ckpt

    session_id = config.get("_session_id")
    if not session_id:
        err("No active session.")
        return True

    arg = args.strip()

    if arg == "clear":
        ckpt.delete_session_checkpoints(session_id)
        info("All checkpoints cleared.")
        return True

    if not arg:
        snaps = ckpt.list_snapshots(session_id)
        if not snaps:
            info("No checkpoints yet.")
            return True
        info(f"Checkpoints ({len(snaps)} total):")
        for s in snaps:
            ts = s["created_at"]
            try:
                t = datetime.fromisoformat(ts).strftime("%H:%M")
            except Exception:
                t = ts[:16]
            preview = s["user_prompt_preview"]
            if preview:
                preview = f'  "{preview[:40]}{"..." if len(preview) > 40 else ""}"'
            else:
                preview = "  (initial state)"
            print(f"  #{s['id']:<3} [turn {s['turn_count']}]  {t}{preview}")
        return True

    try:
        snap_id = int(arg)
    except ValueError:
        err(f"Unknown subcommand: {arg}")
        return True

    snap = ckpt.get_snapshot(session_id, snap_id)
    if snap is None:
        err(f"Checkpoint #{snap_id} not found.")
        return True

    changed = ckpt.files_changed_since(session_id, snap_id)
    ts = snap.created_at
    try:
        t = datetime.fromisoformat(ts).strftime("%H:%M")
    except Exception:
        t = ts[:16]

    info(f"Checkpoint #{snap_id} (turn {snap.turn_count}, {t})")
    if changed:
        shown = changed[:4]
        extra = f" (+{len(changed) - 4} files)" if len(changed) > 4 else ""
        info(f"Files changed since: {', '.join(Path(f).name for f in shown)}{extra}")
    print()
    menu_buf = "  1. Restore conversation + files\n  2. Restore conversation only\n  3. Restore files only\n  4. Cancel"
    print(menu_buf)
    print()

    try:
        choice = ask_input_interactive("Choice [1-4]: ", config, menu_buf).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return True

    restore_conversation = choice in ("1", "2")
    restore_files = choice in ("1", "3")

    if choice == "4" or choice not in ("1", "2", "3"):
        info("Cancelled.")
        return True

    results = []

    if restore_conversation:
        state.messages = state.messages[:snap.message_index]
        state.turn_count = snap.turn_count
        state.total_input_tokens = snap.token_snapshot.get("input", 0)
        state.total_output_tokens = snap.token_snapshot.get("output", 0)
        state.total_cache_read_tokens = snap.token_snapshot.get("cache_read", 0)
        state.total_cache_creation_tokens = snap.token_snapshot.get("cache_creation", 0)
        state.distinct_base = snap.token_snapshot.get("distinct_base", 0)
        results.append("conversation restored")

    if restore_files:
        file_results = ckpt.rewind_files(session_id, snap_id)
        for r in file_results:
            print(f"  {r}")
        results.append(f"{len(file_results)} file(s) processed")

    ckpt.reset_tracked()
    ckpt.make_snapshot(
        session_id, state, config,
        f"[rewind to #{snap_id}]",
        tracked_edits=None,
    )

    info(f"Done: {', '.join(results)}. New checkpoint created.")
    return True


cmd_rewind = cmd_checkpoint
