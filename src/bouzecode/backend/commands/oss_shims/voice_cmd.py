"""OSS shim: /voice command — delegates to the flat voice/ package."""
from __future__ import annotations


def cmd_voice(args: str, config: dict) -> str | None:
    """Handle /voice [start|stop|status]."""
    try:
        from voice import voice_cmd
        return voice_cmd.handle(args, config)
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("Voice feature requires 'sounddevice'. Install with: pip install sounddevice")
        return None
    except AttributeError:
        # voice package exists but doesn't have handle() — try alternate API
        try:
            from voice import transcribe
            from bouzecode.ui.ansi import info
            info("Voice module loaded. Use /voice start to begin recording.")
            return None
        except ImportError:
            from bouzecode.ui.ansi import warn
            warn("Voice module found but no handler available.")
            return None
