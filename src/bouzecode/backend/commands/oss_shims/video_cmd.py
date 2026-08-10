"""OSS shim: /video command — delegates to the flat video/ pipeline package."""
from __future__ import annotations


def cmd_video(args: str, state=None, config: dict | None = None) -> str | None:
    """Handle /video [status|topic|--source <dir>].

    Delegates to the flat commands/video_cmd.py which orchestrates the full
    video pipeline (story → TTS → images → subtitles → assembly).
    """
    if config is None:
        config = {}

    # Try to delegate to the real flat video command
    try:
        from commands.video_cmd import cmd_video as _flat_cmd_video
        return _flat_cmd_video(args, state, config)
    except ImportError as exc:
        # Flat package not available — show dependency status
        pass

    # Fallback: check and report video dependencies
    try:
        from video import check_video_deps
        deps = check_video_deps()
    except ImportError:
        deps = {}

    try:
        from bouzecode.ui.ansi import warn, info
    except ImportError:
        def warn(msg): print(f"Warning: {msg}")
        def info(msg): print(msg)

    missing = [k for k, v in deps.items() if not v]
    if missing:
        warn(f"Video pipeline dependencies missing: {', '.join(missing)}")
        info("Install missing dependencies and retry. Use '/video status' for details.")
    else:
        warn("Video command module not found. Ensure 'commands/' is on PYTHONPATH.")

    return None
