"""OSS shim: /voice command — delegates to the flat voice/ package.

Flow:
  /voice         → record audio via voice.voice_input() → return ("__voice__", text)
  /voice status  → check deps and print availability
"""
from __future__ import annotations


def cmd_voice(args: str, state, config) -> "tuple | None":
    """Handle /voice [status].

    Returns:
        ("__voice__", transcribed_text) on success — REPL sends text to LLM.
        None on failure or status check.
    """
    sub = args.strip().lower()

    # --- /voice status: report dependency availability ---
    if sub == "status":
        return _voice_status()

    # --- /voice (default): record + transcribe ---
    return _voice_record(config)


def _voice_status() -> None:
    """Print voice dependency status."""
    try:
        from voice import check_voice_deps
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("Voice package not installed.")
        return None

    available, reason = check_voice_deps()
    if available:
        from bouzecode.ui.ansi import info
        info("Voice: all dependencies available ✓")
    else:
        from bouzecode.ui.ansi import warn
        warn(f"Voice unavailable: {reason}")
    return None


def _voice_record(config: dict) -> "tuple | None":
    """Record audio and return sentinel tuple for REPL."""
    try:
        from voice import check_voice_deps, voice_input
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn(
            "Voice feature requires the 'voice' package.\n"
            "  Install deps: pip install sounddevice faster-whisper"
        )
        return None

    # Check dependencies before recording
    available, reason = check_voice_deps()
    if not available:
        from bouzecode.ui.ansi import warn
        warn(f"Voice unavailable: {reason}")
        return None

    # Record + transcribe
    from bouzecode.ui.ansi import info
    info("🎤 Listening... (speak, then pause to stop)")
    try:
        text = voice_input(
            language=config.get("voice_language", "auto"),
            max_seconds=config.get("voice_max_seconds", 30),
        )
    except Exception as exc:
        from bouzecode.ui.ansi import warn
        warn(f"Voice recording failed: {exc}")
        return None

    if not text:
        from bouzecode.ui.ansi import warn
        warn("No speech detected.")
        return None

    from bouzecode.ui.ansi import info as info_
    info_(f"📝 Transcribed: {text}")
    return ("__voice__", text)
