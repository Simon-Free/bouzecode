"""OSS shim: /video command — delegates to video/screenshot functionality."""
from __future__ import annotations


def cmd_video(args: str, config: dict) -> str | None:
    """Handle /video [screenshot|record]."""
    try:
        from bouzecode.ui.ansi import info
        info("Video/screenshot feature: use the Image tool for screenshots.")
        return None
    except ImportError:
        return None
