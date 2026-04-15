# [desc] Voice command handler for recording audio, transcribing via STT, and submitting as user input. [/desc]
"""Voice input: record, transcribe via STT, and submit as user message."""

try:
    from ui.ansi import clr, ok, err, info
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
         "red": "\033[31m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def info(msg):  print(clr(msg, "cyan"))
    def ok(msg):    print(clr(msg, "green"))
    def err(msg):   print(clr(f"Error: {msg}", "red"), file=sys.stderr)

from tools.interaction import ask_input_interactive

_voice_language: str = "auto"


def cmd_voice(args: str, state, config) -> bool:
    """Voice input: record -> STT -> auto-submit as user message.

    /voice            — record once, transcribe, submit
    /voice status     — show backend availability
    /voice lang <code> — set STT language (e.g. zh, en, ja; 'auto' to reset)
    /voice device     — list and select input microphone
    """
    global _voice_language

    subcmd = args.strip().lower().split()[0] if args.strip() else ""
    rest = args.strip()[len(subcmd):].strip()

    if subcmd == "device":
        try:
            from voice import list_input_devices
        except ImportError:
            err("sounddevice not available. Install with: pip install sounddevice")
            return True
        try:
            devices = list_input_devices()
        except Exception as e:
            err(f"Could not list devices: {e}")
            return True
        if not devices:
            err("No input devices found.")
            return True
        current = config.get("_voice_device_index")
        print(clr("  🎙  Available input devices:", "cyan", "bold"))
        for d in devices:
            marker = " ◀" if current == d["index"] else ""
            print(f"  {d['index']:3d}. {d['name']}{clr(marker, 'green', 'bold')}")
        sel = ask_input_interactive(clr("  Select device # (Enter to cancel): ", "cyan"), config).strip()
        if sel.isdigit():
            idx = int(sel)
            valid = [d["index"] for d in devices]
            if idx in valid:
                config["_voice_device_index"] = idx
                name = next(d["name"] for d in devices if d["index"] == idx)
                ok(f"Microphone set to: [{idx}] {name}")
            else:
                err(f"Invalid device index: {idx}")
        return True

    if subcmd == "lang":
        if not rest:
            info(f"Current STT language: {_voice_language}  (use '/voice lang auto' to reset)")
            return True
        _voice_language = rest.lower()
        ok(f"STT language set to '{_voice_language}'")
        return True

    if subcmd == "status":
        try:
            from voice import check_voice_deps, check_recording_availability, check_stt_availability
            from voice.stt import get_stt_backend_name
        except ImportError as e:
            err(f"voice package not available: {e}")
            return True

        rec_ok, rec_reason = check_recording_availability()
        stt_ok, stt_reason = check_stt_availability()

        print(clr("  Voice status:", "cyan", "bold"))
        if rec_ok:
            ok("  Recording backend: available")
        else:
            err(f"  Recording: {rec_reason}")
        if stt_ok:
            ok(f"  STT backend:       {get_stt_backend_name()}")
        else:
            err(f"  STT: {stt_reason}")
        dev_idx = config.get("_voice_device_index")
        if dev_idx is not None:
            try:
                from voice import list_input_devices
                devs = list_input_devices()
                dev_name = next((d["name"] for d in devs if d["index"] == dev_idx), f"#{dev_idx}")
            except Exception:
                dev_name = f"#{dev_idx}"
            info(f"  Microphone:    [{dev_idx}] {dev_name}")
        else:
            info("  Microphone:    system default")
        info(f"  Language: {_voice_language}")
        info("  Env override: NANO_CLAUDE_WHISPER_MODEL (default: base)")
        return True

    # /voice [start] — record once and submit
    try:
        from voice import check_voice_deps, voice_input as _voice_input
    except ImportError:
        err("voice/ package not found — this should not happen")
        return True

    available, reason = check_voice_deps()
    if not available:
        err(f"Voice input not available:\n{reason}")
        return True

    _BARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    _last_bar: list[str] = [""]

    def on_energy(rms: float) -> None:
        level = min(int(rms * 8 / 0.08), 8)
        bar = _BARS[level]
        if bar != _last_bar[0]:
            _last_bar[0] = bar
            print(f"\r\033[K  🎙  {bar}  ", end="", flush=True)

    print(clr("  🎙  Listening… (speak now, auto-stops on silence, Ctrl+C to cancel)", "cyan"))

    try:
        text = _voice_input(language=_voice_language, on_energy=on_energy, device_index=config.get("_voice_device_index"))
    except KeyboardInterrupt:
        print()
        info("  Voice input cancelled.")
        return True
    except Exception as e:
        print()
        err(f"Voice input error: {e}")
        return True

    print()

    if not text:
        info("  (nothing transcribed — no speech detected)")
        return True

    ok(f'  Transcribed: \u201c{text}\u201d')
    print()

    return ("__voice__", text)
