# [desc] Implements basic REPL commands: help, clear, model switching, config editing, exit, and permission prompts. [/desc]
"""Basic REPL commands: help, clear, model, config, permissions prompt."""
from __future__ import annotations

import json
import sys

try:
    from ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err

from tools import ask_input_interactive, _is_in_tg_turn


def ask_permission_interactive(desc: str, config: dict) -> bool:
    text = ask_input_interactive(f"  Allow: {desc}  [y/N/a(ccept-all)] ", config).strip().lower()
    if text in ("a", "accept all", "accept-all"):
        config["permission_mode"] = "accept-all"
        if _is_in_tg_turn(config):
            from commands.telegram_cmd import _tg_send
            token = config.get("telegram_token")
            chat_id = config.get("telegram_chat_id")
            _tg_send(token, chat_id, "\u2705 Permission mode set to accept-all for this session.")
        else:
            ok("  Permission mode set to accept-all for this session.")
        return True
    return text in ("y", "yes")


def cmd_help(_args: str, _state, config) -> bool:
    import bouzecode
    print(bouzecode.__doc__)
    return True


def cmd_clear(_args: str, state, config) -> bool:
    state.messages.clear()
    state.turn_count = 0
    state.timing_entries.clear()
    state.conversation_start = 0.0
    state.total_input_tokens = 0
    state.total_output_tokens = 0
    state.total_cache_read_tokens = 0
    state.total_cache_creation_tokens = 0
    state.distinct_base = 0
    state.compaction_log.clear()
    from tools import clear_file_state
    clear_file_state()
    ok("Conversation cleared.")
    return True


def cmd_model(args: str, _state, config) -> bool:
    from providers import PROVIDERS, detect_provider
    if not args:
        model = config["model"]
        pname = detect_provider(model)
        info(f"Current model:    {model}  (provider: {pname})")
        info("\nAvailable models by provider:")
        for pn, pdata in PROVIDERS.items():
            ms = pdata.get("models", [])
            if ms:
                info(f"  {pn:12s}  " + ", ".join(ms[:4]) + ("..." if len(ms) > 4 else ""))
        info("\nFormat: 'provider/model' or just model name (auto-detected)")
        info("  e.g. /model gpt-4o")
        info("  e.g. /model ollama/qwen2.5-coder")
        info("  e.g. /model kimi:moonshot-v1-32k")
    else:
        m = args.strip()
        if "/" not in m and ":" in m:
            left, right = m.split(":", 1)
            if left in PROVIDERS:
                m = f"{left}/{right}"
        config["model"] = m
        pname = detect_provider(m)
        ok(f"Model set to {m}  (provider: {pname})")
        from config import save_config
        save_config(config)
    return True


def cmd_config(args: str, _state, config) -> bool:
    from config import save_config
    if not args:
        display = {k: v for k, v in config.items() if k != "api_key"}
        print(json.dumps(display, indent=2))
    elif "=" in args:
        key, _, val = args.partition("=")
        key, val = key.strip(), val.strip()
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        elif val.isdigit():
            val = int(val)
        config[key] = val
        save_config(config)
        ok(f"Set {key} = {val}")
    else:
        k = args.strip()
        v = config.get(k, "(not set)")
        info(f"{k} = {v}")
    return True


def cmd_exit(_args: str, _state, config) -> bool:
    if sys.stdin.isatty() and sys.platform != "win32":
        sys.stdout.write("\x1b[?2004l")
        sys.stdout.flush()
    ok("Goodbye!")
    config["_session_saved"] = True
    from commands.session import save_latest, _build_session_data
    save_latest("", _state, config)
    if config.get("cloudsave_auto") and config.get("gist_token") and _state.messages:
        info("Auto cloud-sync: uploading session to Gist\u2026")
        from cloudsave import upload_session
        from config import save_config
        session_data = _build_session_data(_state)
        gist_id, err_msg = upload_session(
            session_data, config["gist_token"],
            existing_gist_id=config.get("cloudsave_last_gist_id"),
        )
        if err_msg:
            err(f"Cloud sync failed: {err_msg}")
        else:
            config["cloudsave_last_gist_id"] = gist_id
            save_config(config)
            ok(f"Session synced \u2192 https://gist.github.com/{gist_id}")
    sys.exit(0)


def _interactive_ollama_picker(config: dict) -> bool:
    from providers import PROVIDERS, list_ollama_models
    prov = PROVIDERS.get("ollama", {})
    base_url = prov.get("base_url", "http://localhost:11434")

    models = list_ollama_models(base_url)
    if not models:
        err(f"No local Ollama models found at {base_url}.")
        return False

    menu_buf = clr("\n  \u2500\u2500 Local Ollama Models \u2500\u2500", "dim")
    for i, m in enumerate(models):
        menu_buf += "\n" + clr(f"  [{i+1:2d}] ", "yellow") + m
    print(menu_buf)
    print()

    try:
        ans = ask_input_interactive(clr("  Select a model number or Enter to cancel > ", "cyan"), config, menu_buf).strip()
        if not ans:
            return False
        idx = int(ans) - 1
        if 0 <= idx < len(models):
            new_model = f"ollama/{models[idx]}"
            config["model"] = new_model
            from config import save_config
            save_config(config)
            ok(f"Model updated to {new_model}")
            return True
        else:
            err("Invalid selection.")
    except (ValueError, KeyboardInterrupt, EOFError):
        pass
    return False
