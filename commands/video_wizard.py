# [desc] Interactive step-by-step CLI wizard for configuring /video command parameters. [/desc]
"""Video wizard step loop — interactive config for /video."""
from __future__ import annotations

import os as _os

try:
    from ui.ansi import clr, warn
except ImportError:
    C = {"cyan": "\033[36m", "yellow": "\033[33m", "bold": "\033[1m",
         "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def warn(msg): print(clr(f"Warning: {msg}", "yellow"))

from tools import ask_input_interactive
from commands.video_cmd import (
    _video_pick, _VP_BACK, _VP_QUIT, _VIDEO_LANGUAGES, _detect_lang_from_text,
)

STEP_NAMES = ["mode", "topic", "source", "language", "style", "format",
              "duration", "tts", "images", "quality", "subtitles", "output"]


def run_video_wizard(W: dict, config: dict, is_tg: bool) -> dict | None:
    """Run the interactive wizard. Returns completed *W* dict, or ``None`` on quit."""
    from video.niches import CONTENT_NICHES
    niche_keys = list(CONTENT_NICHES.keys())
    step = 0
    _default_out = _os.path.join(_os.getcwd(), "video_output")

    while step < len(STEP_NAMES):
        sname = STEP_NAMES[step]

        # ── Mode ──────────────────────────────────────────────────────────
        if sname == "mode":
            if is_tg:
                step += 1; continue
            print(clr(f"\n  [0] Content mode", "bold"))
            idx = _video_pick("Pick mode", [
                "Auto         (AI generates story from your topic)",
                "Custom script (you provide the text -- TTS reads it as narration + subtitles)",
            ], config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            if idx == 1:
                W["content_mode"] = "script"
                print(clr("\n  Paste your narration text (type END on a new line when done):", "cyan"))
                lines = []
                try:
                    while True:
                        line = ask_input_interactive("  ", config)
                        if line.strip().upper() == "END": break
                        lines.append(line)
                except (KeyboardInterrupt, EOFError):
                    pass
                W["script_text"] = "\n".join(lines).strip()
                if not W["script_text"]:
                    warn("  No text entered -- switching to AI mode")
                    W["content_mode"] = "ai"
                else:
                    print(clr(f"  -> Script: {len(W['script_text'].split())} words", "dim"))
                    W["subtitle_mode"] = "story"
            else:
                W["content_mode"] = "ai"
            step += 1

        # ── Topic ─────────────────────────────────────────────────────────
        elif sname == "topic":
            if is_tg or W["content_mode"] == "script":
                step += 1; continue
            cur = W["topic"] or ""
            hint = f" [{cur[:50]}...]" if cur else " (Enter for auto)"
            try:
                val = ask_input_interactive(clr(f"  Topic / idea{hint}: ", "cyan"), config).strip()
            except (KeyboardInterrupt, EOFError):
                return None
            if val.lower() in ("q", "quit"): return None
            if val.lower() in ("b", "back"): step = max(0, step - 1); continue
            if val: W["topic"] = val
            step += 1

        # ── Source folder ─────────────────────────────────────────────────
        elif sname == "source":
            if is_tg or W["source_dir"]:
                step += 1; continue
            try:
                src_raw = ask_input_interactive(
                    clr("  Source folder/file (Enter to skip  b=back): ", "cyan"), config
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return None
            if src_raw.lower() in ("q", "quit"): return None
            if src_raw.lower() in ("b", "back"): step = max(0, step - 1); continue
            if src_raw:
                src_raw = _os.path.expanduser(src_raw)
                if _os.path.isfile(src_raw):
                    from video.source import summarise_source_for_story
                    snippet = summarise_source_for_story([src_raw], max_chars=6000)
                    if snippet:
                        t = W["topic"]
                        W["topic"] = (t + "\n\nSource context:\n" + snippet) if t else snippet
                        print(clr(f"  Using file: {_os.path.basename(src_raw)}", "dim"))
                    else:
                        warn(f"  Could not read: {src_raw}")
                elif _os.path.isdir(src_raw):
                    W["source_dir"] = src_raw
                    from video.source import scan_source_dir, summarise_source_for_story
                    si = scan_source_dir(src_raw)
                    for kind, files in si.items():
                        if files: print(clr(f"    {kind}: {len(files)} file(s)", "dim"))
                    if not W["topic"] and si["text"]:
                        W["topic"] = summarise_source_for_story(si["text"])
                        print(clr(f"  Auto-topic: {W['topic'][:80]}...", "dim"))
                else:
                    warn(f"  Path not found: {src_raw}")
            step += 1

        # ── Language ──────────────────────────────────────────────────────
        elif sname == "language":
            print(clr(f"\n  [{step}] Language", "bold"))
            auto_idx = _detect_lang_from_text(W["topic"])
            auto_label = _VIDEO_LANGUAGES[auto_idx][0]
            lang_options = [f"Auto         (detected: {auto_label})"] + \
                           [row[0] for row in _VIDEO_LANGUAGES] + \
                           ["\u270f\ufe0f  Other (type your own)"]
            idx = _video_pick("Pick language", lang_options, config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            if idx == 0:
                W["lang_idx"] = auto_idx
            elif 1 <= idx <= len(_VIDEO_LANGUAGES):
                W["lang_idx"] = idx - 1
            else:
                try:
                    lname = ask_input_interactive(clr("  Language name: ", "cyan"), config).strip()
                    wcode = ask_input_interactive(clr("  Whisper code (e.g. it, th -- Enter to skip): ", "cyan"), config).strip()
                except (KeyboardInterrupt, EOFError):
                    lname, wcode = "English", ""
                W["lang_idx"] = -1
                W["lang_name"] = (lname or "English", wcode or "auto")
            step += 1

        # ── Style / Niche ─────────────────────────────────────────────────
        elif sname == "style":
            if W["content_mode"] == "script":
                step += 1; continue
            print(clr(f"\n  [{step}] Style / Niche", "bold"))
            print(clr("   1.", "cyan") + "  Auto-viral (AI picks best niche)")
            for i, (k, v) in enumerate(CONTENT_NICHES.items(), 2):
                print(clr(f"  {i:2d}.", "cyan") + f"  {v['nombre']}")
            other_n = len(CONTENT_NICHES) + 2
            print(clr(f"  {other_n:2d}.", "cyan") + "  Other (describe your own style)")
            try:
                raw_n = ask_input_interactive(
                    clr("  Pick style  [Enter=Auto  b=back  q=quit]: ", "cyan"), config
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                return None
            if raw_n in ("q", "quit"): return None
            if raw_n in ("b", "back"): step = max(0, step - 1); continue
            if not raw_n or raw_n == "1":
                W["niche_name"] = None
                print(clr("  -> Auto-viral", "dim"))
            elif raw_n.isdigit():
                n = int(raw_n)
                if 2 <= n <= len(CONTENT_NICHES) + 1:
                    W["niche_name"] = niche_keys[n - 2]
                    print(clr(f"  -> {CONTENT_NICHES[W['niche_name']]['nombre']}", "dim"))
                elif n == other_n:
                    try:
                        desc = ask_input_interactive(clr("  Describe style: ", "cyan"), config).strip()
                    except (KeyboardInterrupt, EOFError):
                        desc = ""
                    if desc:
                        t = W["topic"]
                        W["topic"] = (t + "\n\nContent style: " + desc) if t else ("Content style: " + desc)
                        print(clr(f"  -> Custom: {desc}", "dim"))
                    W["niche_name"] = None
                else:
                    W["niche_name"] = None
            elif raw_n in CONTENT_NICHES:
                W["niche_name"] = raw_n
            else:
                t = W["topic"]
                W["topic"] = (t + "\n\nContent style: " + raw_n) if t else ("Content style: " + raw_n)
                W["niche_name"] = None
            step += 1

        # ── Format ────────────────────────────────────────────────────────
        elif sname == "format":
            print(clr(f"\n  [{step}] Format", "bold"))
            idx = _video_pick("Pick format", [
                "Auto         (Landscape 16:9, YouTube standard)",
                "Landscape    16:9  (YouTube)",
                "Short        9:16  (TikTok, Reels, Shorts)",
            ], config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            W["is_short"] = (idx == 2)
            step += 1

        # ── Duration ──────────────────────────────────────────────────────
        elif sname == "duration":
            if W["content_mode"] == "script":
                step += 1; continue
            print(clr(f"\n  [{step}] Duration", "bold"))
            dur_choices = ["Auto         (~2 min, recommended)", "~30 sec      (short clip)",
                           "~1 min", "~2 min", "~3 min", "~5 min", "Custom       (type any length)"]
            dur_values = [2.0, 0.5, 1.0, 2.0, 3.0, 5.0, None]
            idx = _video_pick("Pick duration", dur_choices, config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            dv = dur_values[idx]
            if dv is None:
                try:
                    raw_d = ask_input_interactive(clr("  Minutes (e.g. 4.5): ", "cyan"), config).strip()
                    dv = float(raw_d) if raw_d else 2.0
                except (ValueError, KeyboardInterrupt, EOFError):
                    dv = 2.0
            W["duration_min"] = dv
            step += 1

        # ── TTS Voice ─────────────────────────────────────────────────────
        elif sname == "tts":
            print(clr(f"\n  [{step}] Voice (TTS)", "bold"))
            _has_gemini = bool(_os.getenv("GEMINI_API_KEY"))
            _has_eleven = bool(_os.getenv("ELEVENLABS_API_KEY"))
            li = W["lang_idx"]
            _ev = _VIDEO_LANGUAGES[li][2] if (li is not None and 0 <= li < len(_VIDEO_LANGUAGES)) else "en-US-GuyNeural"
            tts_options = [
                "Auto         (Gemini -> ElevenLabs -> Edge)",
                f"Edge TTS     (free)  voice={_ev}",
                f"Gemini TTS   {'\u2713' if _has_gemini else '\u2717 needs GEMINI_API_KEY'}",
                f"ElevenLabs   {'\u2713' if _has_eleven else '\u2717 needs ELEVENLABS_API_KEY'}",
            ]
            tts_engines = ["auto", "edge", "gemini", "elevenlabs"]
            idx = _video_pick("Pick voice engine", tts_options, config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            W["tts_engine"] = tts_engines[idx]
            step += 1

        # ── Images ────────────────────────────────────────────────────────
        elif sname == "images":
            print(clr(f"\n  [{step}] Images", "bold"))
            img_options = [
                "Auto         (Gemini Web -> Web Search -> Placeholder)",
                "Web Search   (free stock photos, no login needed)",
                "Gemini Web   (Imagen 3, needs 1-time browser login)",
                "Placeholder  (gradient slides, always works)",
            ]
            img_engines = ["auto", "web-search", "gemini-web", "placeholder"]
            idx = _video_pick("Pick image source", img_options, config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            W["image_engine"] = img_engines[idx]
            step += 1

        # ── Quality ───────────────────────────────────────────────────────
        elif sname == "quality":
            print(clr(f"\n  [{step}] Video Quality", "bold"))
            q_options = [
                "Auto         (Medium -- good balance)", "High         (CRF 18, slow -- best quality)",
                "Medium       (CRF 23, balanced)", "Low          (CRF 28, fast)",
                "Minimal      (CRF 32, fastest -- for testing)",
            ]
            q_values = ["medium", "high", "medium", "low", "minimal"]
            idx = _video_pick("Pick quality", q_options, config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            W["quality"] = q_values[idx]
            step += 1

        # ── Subtitles ─────────────────────────────────────────────────────
        elif sname == "subtitles":
            print(clr(f"\n  [{step}] Subtitles", "bold"))
            sub_options = [
                "Auto         (Whisper transcription -- requires faster-whisper)",
                "Story text   (burn story script as subtitles -- works for all languages)",
                "Custom text  (type or paste your own subtitle text)",
                "None         (no subtitles)",
            ]
            idx = _video_pick("Pick subtitle mode", sub_options, config, default=1)
            if idx == _VP_QUIT: return None
            if idx == _VP_BACK: step = max(0, step - 1); continue
            if idx == 0:
                W["subtitle_mode"] = "auto"
            elif idx == 1:
                W["subtitle_mode"] = "story"
                print(clr("  -> Will use story text as subtitles (no Whisper needed)", "dim"))
            elif idx == 2:
                W["subtitle_mode"] = "custom"
                print(clr("  Paste subtitle text (type END on a new line when done):", "cyan"))
                lines = []
                try:
                    while True:
                        line = ask_input_interactive("  ", config)
                        if line.strip().upper() == "END": break
                        lines.append(line)
                except (KeyboardInterrupt, EOFError):
                    pass
                W["subtitle_text"] = "\n".join(lines).strip()
                if W["subtitle_text"]:
                    preview = W["subtitle_text"][:80].replace('\n', ' ')
                    print(clr(f"  -> Custom text: {preview}{'...' if len(W['subtitle_text']) > 80 else ''}", "dim"))
                else:
                    print(clr("  -> No text entered, falling back to Auto", "dim"))
                    W["subtitle_mode"] = "auto"
            else:
                W["subtitle_mode"] = "none"
                print(clr("  -> No subtitles", "dim"))
            step += 1

        # ── Output path ───────────────────────────────────────────────────
        elif sname == "output":
            print(clr(f"\n  [{step}] Output path", "bold"))
            print(f"  Default: {_default_out}")
            try:
                val = ask_input_interactive(
                    clr("  Custom dir (Enter=default  b=back  q=quit): ", "cyan"), config
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return None
            if val.lower() in ("q", "quit"): return None
            if val.lower() in ("b", "back"): step = max(0, step - 1); continue
            W["output_dir"] = val if val else _default_out
            step += 1

    return W
