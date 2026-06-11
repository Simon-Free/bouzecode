# [desc] Basic REPL commands: help, clear, model switching, config editing, exit, and permission prompts. [/desc]
"""Basic REPL commands: help, clear, model, config, permissions prompt."""
from __future__ import annotations

import json
import sys

try:
    from bouzecode.ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err

from bouzecode.backend.tools import ask_input_interactive


def ask_permission_interactive(desc: str, config: dict) -> bool:
    text = ask_input_interactive(f"  Allow: {desc}  [y/N/a(ccept-all)] ", config).strip().lower()
    if text in ("a", "accept all", "accept-all"):
        config["permission_mode"] = "accept-all"
        ok("  Permission mode set to accept-all for this session.")
        return True
    return text in ("y", "yes")


def cmd_help(_args: str, _state, config) -> bool:
    import bouzecode
    print(bouzecode.__doc__)
    return True


def cmd_clear(_args: str, state, config) -> bool:
    import uuid
    if state.messages:
        from ..session.session import save_latest
        save_latest("", state, config)
    state.messages.clear()
    state.turn_count = 0
    state.user_loop_count = 0
    state.total_tool_calls = 0
    state.timing_entries.clear()
    state.conversation_start = 0.0
    state.total_input_tokens = 0
    state.total_output_tokens = 0
    state.total_cache_read_tokens = 0
    state.total_cache_creation_tokens = 0
    state.distinct_base = 0
    state.compaction_log.clear()
    state.context_state.notes.clear()
    state.notes_timeline.clear()
    state.thinking_log.clear()
    from bouzecode.backend.tools import clear_file_state
    clear_file_state()
    config.pop("_session_path", None)
    config["_session_id"] = uuid.uuid4().hex[:8]
    ok("Conversation cleared.")
    return True


def cmd_model(args: str, _state, config) -> bool:
    from ...agent.providers import PROVIDERS, detect_provider
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
        from bouzecode.backend.core.config import save_config
        save_config(config)
    return True


def cmd_config(args: str, _state, config) -> bool:
    from bouzecode.backend.core.config import save_config
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
    from ..session.session import save_latest, _build_session_data
    save_latest("", _state, config)
    sys.exit(0)





def cmd_tools(args: str, _state, config) -> bool:
    """List, enable, or disable tools."""
    from bouzecode.backend.core.tool_registry import (
        get_all_tools, disable_tool, enable_tool,
        is_enabled, list_disabled, reset_disabled,
    )

    args = args.strip()

    if not args:
        tools = get_all_tools()
        if not tools:
            print("No tools registered.")
            return True
        disabled = set(list_disabled())
        for t in tools:
            status = "[disabled]" if t.name in disabled else "[enabled]"
            print(f"  {status} {t.name}")
        return True

    parts = args.split(maxsplit=1)
    sub = parts[0].lower()
    tool_name = parts[1].strip() if len(parts) > 1 else ""

    if sub == "disable" and tool_name:
        try:
            disable_tool(tool_name)
            ok(f"Disabled tool: {tool_name}")
        except KeyError:
            err(f"Unknown tool: {tool_name}")
    elif sub == "enable" and tool_name:
        enable_tool(tool_name)
        ok(f"Enabled tool: {tool_name}")
    elif sub == "reset":
        reset_disabled()
        ok("All tools re-enabled.")
    else:
        info("Usage: /tools [disable <name> | enable <name> | reset]")

    return True
