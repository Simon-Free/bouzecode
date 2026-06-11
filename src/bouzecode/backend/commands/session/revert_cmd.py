# [desc] Reverts file changes and conversation state to the most recent checkpoint snapshot. [/desc]
"""Revert all file changes and conversation state to the last user input."""
from bouzecode.backend import checkpoint as ckpt
from bouzecode.backend.checkpoint.store import _load_snapshots
from bouzecode.ui.ansi import info, err


def cmd_revert(args, state, config) -> bool:
    session_id = config.get("_session_id")
    if not session_id:
        err("No active session — cannot revert.")
        return True

    snapshots = _load_snapshots(session_id)
    if not snapshots:
        err("No checkpoints available to revert to.")
        return True

    target = None
    for s in reversed(snapshots):
        if s.message_index < len(state.messages):
            target = s
            break

    if target is None:
        target = snapshots[0]

    snap_id = target.id

    state.messages = state.messages[:target.message_index]
    state.turn_count = target.turn_count
    state.user_loop_count = getattr(target, "user_loop_count", 0)
    token_snap = target.token_snapshot
    state.total_input_tokens = token_snap.get("input", 0)
    state.total_output_tokens = token_snap.get("output", 0)
    state.total_cache_read_tokens = token_snap.get("cache_read", 0)
    state.total_cache_creation_tokens = token_snap.get("cache_creation", 0)
    state.distinct_base = token_snap.get("distinct_base", 0)

    file_results = ckpt.rewind_files(session_id, snap_id)
    for r in file_results:
        print(f"  {r}")

    ckpt.reset_tracked()
    ckpt.make_snapshot(
        session_id, state, config,
        f"[revert to #{snap_id}]",
        tracked_edits=None,
    )

    info(f"Reverted to checkpoint #{snap_id}: {len(file_results)} file(s) restored, conversation reset.")
    return True
