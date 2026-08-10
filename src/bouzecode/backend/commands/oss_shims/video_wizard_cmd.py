"""OSS shim: /video-wizard command — delegates to the flat video wizard."""
from __future__ import annotations


def cmd_video_wizard(args: str, state=None, config: dict | None = None) -> str | None:
    """Handle /video-wizard — interactive step-by-step video configuration.

    Delegates to flat commands/video_wizard.py run_video_wizard().
    """
    if config is None:
        config = {}

    try:
        from commands.video_wizard import run_video_wizard
    except ImportError:
        try:
            from bouzecode.ui.ansi import warn
        except ImportError:
            def warn(msg): print(f"Warning: {msg}")
        warn("Video wizard requires the 'commands' and 'video' packages on PYTHONPATH.")
        return None

    # Build initial wizard state dict
    wizard_state: dict = {}
    if args.strip():
        wizard_state["topic"] = args.strip()

    is_tg = False  # Not running in Telegram context
    result = run_video_wizard(wizard_state, config, is_tg)
    if result is None:
        return None

    # Wizard completed — run the pipeline with collected params
    try:
        from commands.video_cmd import cmd_video as _flat_cmd_video
        # Re-invoke with the topic from wizard
        topic = result.get("topic", "")
        return _flat_cmd_video(topic, state, config)
    except ImportError:
        try:
            from bouzecode.ui.ansi import warn
        except ImportError:
            def warn(msg): print(f"Warning: {msg}")
        warn("Video command module not found after wizard completion.")
        return None
