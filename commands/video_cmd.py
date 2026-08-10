# [desc] Interactive CLI wizard for AI-powered viral video generation with language selection and navigation. [/desc]
"""/video command — AI-powered viral video content factory."""
from __future__ import annotations

import os as _os

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

# ── Constants ─────────────────────────────────────────────────────────────
_VP_BACK = -1   # sentinel: user wants to go back
_VP_QUIT = -2   # sentinel: user wants to quit

_VIDEO_LANGUAGES = [
    # (label,         whisper_code, edge_voice,                  story_instruction)
    ("\U0001f1e8\U0001f1f3 Chinese",    "zh", "zh-CN-YunxiNeural",         "Write the story ENTIRELY in Simplified Chinese."),
    ("\U0001f1fa\U0001f1f8 English",    "en", "en-US-GuyNeural",           "Write the story ENTIRELY in English."),
    ("\U0001f1ea\U0001f1f8 Spanish",    "es", "es-ES-AlvaroNeural",        "Write the story ENTIRELY in Spanish."),
    ("\U0001f1ef\U0001f1f5 Japanese",   "ja", "ja-JP-KeitaNeural",         "Write the story ENTIRELY in Japanese."),
    ("\U0001f1f0\U0001f1f7 Korean",     "ko", "ko-KR-InJoonNeural",        "Write the story ENTIRELY in Korean."),
    ("\U0001f1eb\U0001f1f7 French",     "fr", "fr-FR-HenriNeural",         "Write the story ENTIRELY in French."),
    ("\U0001f1e9\U0001f1ea German",     "de", "de-DE-ConradNeural",        "Write the story ENTIRELY in German."),
    ("\U0001f1f5\U0001f1f9 Portuguese", "pt", "pt-BR-AntonioNeural",       "Write the story ENTIRELY in Portuguese."),
    ("\U0001f1f7\U0001f1fa Russian",    "ru", "ru-RU-DmitryNeural",        "Write the story ENTIRELY in Russian."),
    ("\U0001f310 Auto",                 "auto", "en-US-GuyNeural",         ""),
]


def _video_pick(prompt: str, options: list[str], config, default: int | None = None) -> int:
    """Show a numbered list, return 0-based index.
    Returns _VP_BACK (-1) if user types 'b', _VP_QUIT (-2) if user types 'q'.
    """
    for i, opt in enumerate(options, 1):
        marker = clr(f"  {i:>2}.", "cyan")
        print(f"{marker} {opt}")
    default_hint = f"Enter={default}" if default else "Enter=1"
    print(clr(f"  [{default_hint}  b=back  q=quit]", "dim"))
    try:
        raw = ask_input_interactive(clr(f"  {prompt}: ", "cyan"), config).strip().lower()
    except (KeyboardInterrupt, EOFError):
        return _VP_QUIT
    if raw in ("b", "back"):
        return _VP_BACK
    if raw in ("q", "quit", "exit", "0"):
        return _VP_QUIT
    if not raw and default:
        return default - 1
    if raw.isdigit():
        n = int(raw) - 1
        if 0 <= n < len(options):
            return n
    return (default - 1) if default else 0


def _detect_lang_from_text(text: str) -> int:
    """Return index into _VIDEO_LANGUAGES based on script detection, or 1 (English)."""
    if not text:
        return 1
    cjk   = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    kana  = sum(1 for c in text if '\u3040' <= c <= '\u30ff')
    hangu = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    cyr   = sum(1 for c in text if '\u0400' <= c <= '\u04ff')
    total = max(len(text), 1)
    if cjk / total > 0.05:   return 0  # Chinese
    if kana / total > 0.02:  return 3  # Japanese
    if hangu / total > 0.02: return 4  # Korean
    if cyr / total > 0.05:   return 8  # Russian
    return 1  # English


def cmd_video(args: str, _state, config) -> bool:
    """AI-powered viral video content factory -- full number-selection wizard.

    Usage:
      /video [topic]          Launch interactive wizard
      /video status           Show dependency status
      /video --source <dir>   Pre-load images/audio/text from a folder
    """
    from video import check_video_deps
    from video.niches import CONTENT_NICHES

    sub = args.strip().split()[0].lower() if args.strip() else ""

    # ── /video status ─────────────────────────────────────────────────────
    if sub == "status":
        deps = check_video_deps()
        print(clr("\n  Video Pipeline Dependencies\n", "bold"))
        dep_rows = [
            ("ffmpeg",         deps.get("ffmpeg"),        "Video assembly"),
            ("ffprobe",        deps.get("ffprobe"),       "Audio duration probe"),
            ("edge-tts",       deps.get("edge_tts"),      "Free TTS  ->  pip install edge-tts"),
            ("faster-whisper", deps.get("faster_whisper"), "Subtitles ->  pip install faster-whisper"),
            ("playwright",     deps.get("playwright"),    "Gemini Web images ->  pip install playwright"),
            ("Pillow",         deps.get("pillow"),        "Image tools ->  pip install Pillow"),
            ("imageio-ffmpeg", deps.get("ffmpeg"),        "No-sudo ffmpeg ->  pip install imageio-ffmpeg"),
        ]
        for name, dep_flag, note in dep_rows:
            mark = clr("\u2713", "green") if dep_flag else clr("\u2717", "red")
            print(f"  {mark}  {name:<18} {note}")
        print()
        for key, label in [("GEMINI_API_KEY", "Gemini TTS + story"), ("ELEVENLABS_API_KEY", "ElevenLabs TTS")]:
            val = _os.getenv(key, "")
            mark = clr("\u2713", "green") if val else clr("-", "dim")
            print(f"  {mark}  {key:<22} {label}")
        print()
        return True

    # ── Parse --source flag ───────────────────────────────────────────────
    source_dir: str | None = None
    topic_parts: list[str] = []
    tokens = args.split()
    i = 0
    while i < len(tokens):
        if tokens[i] == "--source" and i + 1 < len(tokens):
            source_dir = _os.path.expanduser(tokens[i + 1]); i += 2
        elif tokens[i] == "status":
            i += 1
        else:
            topic_parts.append(tokens[i]); i += 1
    topic_from_args = " ".join(topic_parts).strip()
    is_tg = config.get("_telegram_incoming", False)

    # ── Wizard state ──────────────────────────────────────────────────────
    W: dict = {
        "content_mode": "ai", "script_text": "", "topic": topic_from_args,
        "source_dir": source_dir, "lang_idx": None, "lang_name": "",
        "niche_name": None, "is_short": False, "duration_min": 2.0,
        "tts_engine": "auto", "image_engine": "auto", "quality": "medium",
        "subtitle_mode": "auto", "subtitle_text": "", "output_dir": None,
    }

    print(clr("\n\u256d\u2500 \U0001f3ac Video Content Factory \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e", "bold"))
    print(clr("\u2502  Enter=Auto on every step  \u00b7  b=back  \u00b7  q=quit         \u2502", "dim"))
    print(clr("\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f\n", "bold"))

    from commands.video_wizard import run_video_wizard
    result_W = run_video_wizard(W, config, is_tg)
    if result_W is None:
        return True

    # ── Resolve language settings ─────────────────────────────────────────
    li = result_W["lang_idx"]
    if li is None:
        li = _detect_lang_from_text(result_W["topic"])
    if li == -1:
        lname, wcode = result_W["lang_name"]
        subtitle_lang, edge_voice = wcode, "en-US-GuyNeural"
        story_lang_instr = f"Write the story ENTIRELY in {lname}."
        _lang_display = lname
    elif 0 <= li < len(_VIDEO_LANGUAGES):
        _, subtitle_lang, edge_voice, story_lang_instr = _VIDEO_LANGUAGES[li]
        _lang_display = _VIDEO_LANGUAGES[li][0]
    else:
        subtitle_lang, edge_voice, story_lang_instr = "en", "en-US-GuyNeural", ""
        _lang_display = "English"

    topic        = result_W["topic"]
    source_dir   = result_W["source_dir"]
    niche_name   = result_W["niche_name"]
    is_short     = result_W["is_short"]
    duration_min = result_W["duration_min"]
    tts_engine   = result_W["tts_engine"]
    image_engine = result_W["image_engine"]
    quality      = result_W["quality"]
    output_dir   = result_W["output_dir"] or _os.path.join(_os.getcwd(), "video_output")
    script_text  = result_W["script_text"] if result_W["content_mode"] == "script" else None

    _sub_mode = result_W.get("subtitle_mode", "auto")
    if _sub_mode == "none":       subtitle_text = ""
    elif _sub_mode == "story":    subtitle_text = "__story__"
    elif _sub_mode == "custom" and result_W.get("subtitle_text"):
        subtitle_text = result_W["subtitle_text"]
    else:                         subtitle_text = None

    # ── Summary + confirm ─────────────────────────────────────────────────
    fmt_label = "Short 9:16" if is_short else "Landscape 16:9"
    _sub_label = {"auto": "Whisper auto", "story": "Script text", "none": "None"}.get(
        _sub_mode, f"Custom ({len(result_W.get('subtitle_text',''))} chars)")
    print(clr("\n\u256d\u2500 Settings Summary \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e", "dim"))
    if script_text:
        wc = len(script_text.split())
        print(f"  Mode:     Custom script ({wc} words)")
        print(f"  Script:   {script_text[:70].replace(chr(10),' ')}{'...' if len(script_text)>70 else ''}")
    else:
        print(f"  Topic:    {(topic or '(auto)')[:70]}")
        print(f"  Niche:    {niche_name or 'auto-viral'}")
    print(f"  Language: {_lang_display}")
    print(f"  Format:   {fmt_label}" + ("" if script_text else f"  |  Duration: {duration_min} min"))
    print(f"  Voice:    {tts_engine}  |  Images: {image_engine}  |  Quality: {quality}")
    print(f"  Subtitles: {_sub_label}")
    if source_dir:
        print(f"  Source:   {source_dir}")
    print(f"  Output:   {output_dir}")
    print(f"  Model:    {config['model']}")
    print(clr("\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f", "dim"))

    _default_out = _os.path.join(_os.getcwd(), "video_output")
    if not is_tg:
        try:
            go = ask_input_interactive(
                clr("\n  Start? [Y/n/b=redo last step]: ", "cyan"), config
            ).strip().lower()
            if go in ("b", "back"):
                from commands.video_wizard import STEP_NAMES
                step = len(STEP_NAMES) - 1
                while step < len(STEP_NAMES):
                    sname = STEP_NAMES[step]
                    if sname == "output":
                        print(clr(f"\n  [{step}] Output path", "bold"))
                        print(f"  Default: {_default_out}")
                        try:
                            val = ask_input_interactive(
                                clr("  Custom dir (Enter=default  b=back): ", "cyan"), config
                            ).strip()
                        except (KeyboardInterrupt, EOFError):
                            return True
                        if val.lower() in ("b", "back"):
                            step = max(0, step - 1); continue
                        result_W["output_dir"] = val if val else _default_out
                        output_dir = result_W["output_dir"]
                    step += 1
            elif go in ("n", "no", "q", "quit"):
                return True
        except (KeyboardInterrupt, EOFError):
            return True

    # ── Run pipeline ──────────────────────────────────────────────────────
    from video.pipeline import create_video_story

    this_pkg     = _os.path.dirname(_os.path.abspath(__file__))
    versions_dir = _os.path.dirname(_os.path.dirname(this_pkg))
    sounds_dir   = _os.path.join(versions_dir, "v-content-creator", "sounds")
    if not _os.path.isdir(sounds_dir):
        sounds_dir = None

    result = create_video_story(
        topic=topic, model=config["model"], config=config,
        script_text=script_text, niche_name=niche_name,
        duration_min=duration_min, is_short=is_short,
        tts_engine=tts_engine, edge_voice=edge_voice,
        image_engine=image_engine, quality=quality,
        subtitle_lang=subtitle_lang if subtitle_lang != "auto" else "en",
        subtitle_text=subtitle_text, sounds_dir=sounds_dir,
        source_dir=source_dir, story_lang_instr=story_lang_instr,
        output_dir=output_dir,
    )

    if result:
        ok(f"Video ready: {result['video_path']}  ({result['size_mb']} MB)")
        if result.get('srt_path'):
            info(f"Subtitles:   {result['srt_path']}")
    else:
        warn("Video generation failed. Run /video status to check dependencies.")
    return True
