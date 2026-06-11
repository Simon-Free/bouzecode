#!/usr/bin/env python3
# [desc] CLI entry point and re-exports for bouzécode, a minimal Python implementation of Claude Code. [/desc]
"""
bouzécode (based on cheetahclaws) — Minimal Python implementation of Claude Code.

Usage:
  python bouzecode.py [options] [prompt]

Options:
  -p, --print          Non-interactive: run prompt and exit (also --print-output)
  -m, --model MODEL    Override model
  --cwd PATH           Set working directory (default: launch directory)
  --accept-all         Never ask permission (dangerous)
  --verbose            Show thinking + token counts
  --loud               Think-out-loud mode (visible reasoning)
  --version            Print version and exit

Slash commands in REPL:
  /help       Show this help
  /clear      Clear conversation
  /model [m]  Show or set model
  /config     Show config / set key=value
  /save [f]   Save session to file
  /load [f]   Load session from file
  /history    Print conversation history
  /context    Show context window usage
  /cost       Show API cost this session
  /timing     Show time spent per tool and in LLM calls
  /verbose    Toggle verbose mode
  /thinking   Cycle thinking: off / extended / loud
  /permissions [mode]  Set permission mode
  /cwd [path] Show or change working directory
  /memory [query]         Show/search persistent memories
  /memory consolidate     Extract long-term insights from current session via AI
  /skills           List available skills
  /agents           Show sub-agent tasks
  /mcp              List MCP servers and their tools
  /mcp reload       Reconnect all MCP servers
  /mcp add <n> <cmd> [args]  Add a stdio MCP server
  /mcp remove <n>   Remove an MCP server from config
  /plugin           List installed plugins
  /plugin install name@url   Install a plugin
  /plugin uninstall name     Uninstall a plugin
  /plugin enable/disable name  Toggle plugin
  /plugin update name        Update a plugin
  /plugin recommend [ctx]    Recommend plugins for context
  /tasks            List all tasks
  /tasks create <subject>    Quick-create a task
  /tasks start/done/cancel <id>  Update task status
  /tasks delete <id>         Delete a task
  /tasks get <id>            Show full task details
  /tasks clear               Delete all tasks
  /proactive [dur]  Background sentinel polling (e.g. /proactive 5m)
  /proactive off    Disable proactive polling
  /exit /quit Exit
"""
from __future__ import annotations

import argparse
import os
import sys
from .ansi import C, clr, info, ok, warn, err
from .rendering import (
    console, _RICH, _accumulated_text, _current_live, _live_overflow,
    _overflow_lines_buf, stream_text, stream_thinking, flush_response,
)
from .spinner import _start_tool_spinner, _stop_tool_spinner
from .tool_display import (
    print_tool_start, print_tool_end, render_diff, _last_diffs, _fmt_duration,
)
from bouzecode.backend.commands import (
    COMMANDS, handle_slash, setup_readline,
    save_latest, _build_session_data, _tg_send,
)
from bouzecode.backend.commands.misc import cmd_init, cmd_export, cmd_copy, cmd_diff
from bouzecode.backend.tools import ask_input_interactive, _tg_thread_local, _is_in_tg_turn


if sys.platform == "win32":
    os.system("")  # Enable ANSI escape codes on Windows CMD

# Pre-scan sys.argv before any import triggers MCP auto-init (tools → mcp.tools → background connect).
# Env var is read in mcp/config.py at config-load time.
if "--enable-chrome-devtools" in sys.argv:
    os.environ["BOUZECODE_ENABLE_CHROME_DEVTOOLS"] = "1"

VERSION = __import__("importlib.metadata", fromlist=["version"]).version("bouzecode")

# Backward-compat re-exports — some tools/tests still `from bouzecode import X`.


def _list_available_versions(current: str) -> None:
    """List git tags as available versions, marking the current one."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "tag", "--sort=-v:refname"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__) or ".",
        )
        tags = [t.strip() for t in result.stdout.splitlines() if t.strip().startswith("v")]
    except Exception:
        tags = []
    if not tags:
        print("  (no version tags found)")
        return
    print("\nAvailable versions:")
    for tag in tags:
        ver = tag.lstrip("v")
        marker = "  <-- current" if ver == current else ""
        print(f"  {tag}{marker}")
    print(f"\nUsage: bouzecode --version {tags[1].lstrip('v') if len(tags) > 1 else 'X.Y.Z'}")


def _switch_to_version(version: str) -> None:
    """Spawn the detached self-update script to switch to a given version."""
    import subprocess
    tag = version if version.startswith("v") else f"v{version}"
    script = os.path.join(os.path.dirname(__file__) or ".", "bouzecode_self_update_detached.ps1")
    if not os.path.isfile(script):
        print(f"Error: self-update script not found: {script}", file=sys.stderr)
        sys.exit(1)
    print(f"Switching to bouz\u00e9code {tag}...")
    subprocess.Popen(
        ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", script, "-Version", tag],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )


def strip_unpaired_surrogates(raw: str) -> str:
    """Windows clipboard paste can leave unpaired UTF-16 surrogates that the
    Anthropic SDK cannot encode to UTF-8. Recombine valid high+low pairs via
    UTF-16 round-trip, then drop any orphans via UTF-8 round-trip."""
    recombined = raw.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return recombined.encode("utf-8", "replace").decode("utf-8", "replace")


def _ensure_ripgrep() -> None:
    """Auto-install ripgrep if missing — downloads from GitHub releases."""
    import subprocess, os, sys
    # 1. Already on PATH?
    try:
        subprocess.run(["rg", "--version"], capture_output=True, check=True)
        return
    except Exception:
        pass
    # 2. Check ~/.local/bin (our install location)
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
    rg_path = os.path.join(local_bin, "rg.exe")
    if os.path.isfile(rg_path):
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")
        return
    # 3. Download from GitHub
    print("\033[33m⚠ ripgrep (rg) non trouvé — téléchargement depuis GitHub...\033[0m", flush=True)
    try:
        import urllib.request, zipfile, tempfile
        version = "14.1.1"
        url = f"https://github.com/BurntSushi/ripgrep/releases/download/{version}/ripgrep-{version}-x86_64-pc-windows-msvc.zip"
        os.makedirs(local_bin, exist_ok=True)
        zip_path = os.path.join(tempfile.gettempdir(), "ripgrep.zip")
        print(f"  Téléchargement de ripgrep {version}...", flush=True)
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                basename = os.path.basename(member)
                if basename == "rg.exe":
                    with zf.open(member) as src, open(rg_path, "wb") as dst:
                        dst.write(src.read())
                    break
        os.remove(zip_path)
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")
        # Verify
        subprocess.run([rg_path, "--version"], capture_output=True, check=True)
        print("\033[32m✓ ripgrep installé avec succès.\033[0m", flush=True)
    except Exception as exc:
        print(
            f"\033[31m✗ Échec de l'installation automatique de ripgrep: {exc}\033[0m\n"
            "  → Télécharger manuellement: https://github.com/BurntSushi/ripgrep/releases",
            flush=True,
        )


def main() -> None:
    # Windows consoles default to cp1252, which can't encode the é / box-drawing
    # chars in our UI and crashes mid-output. Force UTF-8 (replace on failure).
    for _stream in (sys.stdout, sys.stderr):
        _reconfig = getattr(_stream, "reconfigure", None)
        if _reconfig is not None:
            try:
                _reconfig(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    parser = argparse.ArgumentParser(
        prog="bouzecode",
        description="bouz\u00e9code (based on cheetahclaws) \u2014 minimal Python Claude Code implementation",
        add_help=False,
    )
    parser.add_argument("prompt", nargs="*", help="Initial prompt (non-interactive)")
    parser.add_argument("--cwd",
                        default=os.environ.get("BOUZECODE_LAUNCH_CWD", os.getcwd()),
                        help="Set working directory (default: launch directory)")
    parser.add_argument("-p", "--print", "--print-output",
                        dest="print_mode", action="store_true",
                        help="Non-interactive mode: run prompt and exit")
    parser.add_argument("-m", "--model", help="Override model")
    parser.add_argument("--accept-all", action="store_true",
                        help="Never ask permission (accept all operations)")
    parser.add_argument("--verbose", action="store_true", help="Show thinking + token counts")
    parser.add_argument("--thinking", action="store_true", help="Enable extended thinking")
    parser.add_argument("--loud", action="store_true", help="Think-out-loud mode (visible <thinking> tags)")
    parser.add_argument("--plan-output", help="Save final response as markdown to this file path")
    parser.add_argument("--session-file", help="Save session state (messages) after each tool round")
    parser.add_argument("--resume-from", help="Resume from a saved session file (restore messages)")
    parser.add_argument("--web-agent-dir", help="Run as a BouzéqUI web agent: IPC dir for state/followup/answer/cancel")
    parser.add_argument("--resume-pending", action="store_true",
                        help="Resume a paused turn (AskUserQuestion): load <session>.pending.json, inject the prompt as answer, finish remaining tool_calls")
    parser.add_argument("--resume-auto", action="store_true",
                        help="Resume a crashed session: complete unresolved tool_calls and call LLM, without injecting a 'Continue.' user message")
    parser.add_argument("--extra-dir", action="append", default=[],
                        help="Extra .bouzecode-structured directory for skills/MCP/plugins (repeatable, highest priority)")
    parser.add_argument("--profile", default="",
                        help="Agent profile name from .bouzecode/profiles/ applied to the top-level agent (bypasses task classification)")
    parser.add_argument("--monitor", action="store_true",
                        help="Shortcut for --profile monitor (supervisor/orchestrator mode)")
    parser.add_argument("--enable-chrome-devtools", action="store_true",
                        help="Enable the chrome-devtools MCP server (disabled by default to save ~5k tokens)")
    parser.add_argument("--result-file", help="Write last assistant message to this file on exit (used by sub-agent terminal mode)")
    parser.add_argument("--version", nargs="?", const="__show__", default=None,
                        metavar="X.Y.Z",
                        help="Print version and list tags, or switch to a specific version")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")

    args = parser.parse_args()

    # Apply --cwd before anything else (config loading, prompt building, etc.)
    os.chdir(args.cwd)

    _ensure_ripgrep()

    if args.version is not None:
        if args.version == "__show__":
            print(f"bouz\u00e9code v{VERSION}")
            _list_available_versions(VERSION)
            sys.exit(0)
        else:
            _switch_to_version(args.version)
            sys.exit(0)
    if args.help:
        print(__doc__)
        sys.exit(0)

    from bouzecode.backend.core.config import load_config, has_api_key
    from bouzecode.backend.agent.providers import detect_provider, PROVIDERS
    from bouzecode.backend.core.paths import register_extra_dirs

    config = load_config()
    # Real sessions recover a missing Methodology / un-snippeted reads via forced
    # side-calls that augment the batch BEFORE execution. enforce_methodology is plain
    # (no in-wire bounce/stash), so this can't loop or duplicate. The e2e harness calls
    # run() directly (not this entry), so it stays opt-in there.
    config["recover_memory"] = True

    # Collect extra dirs: explicit --extra-dir + auto-detected .bouzecode/ in cwd
    extra_dirs = list(args.extra_dir)
    if os.path.isdir(".bouzecode"):
        extra_dirs.append(os.path.abspath(".bouzecode"))
    if extra_dirs:
        register_extra_dirs(extra_dirs)

    if args.monitor:
        args.profile = "monitor"
    if args.profile:
        # Pre-empts task classification (loop.py only classifies when the key is absent).
        config["_task_classification_result"] = args.profile
    if args.model:
        m = args.model
        if "/" not in m and ":" in m:
            left, _ = m.split(":", 1)
            if left in PROVIDERS:
                m = m.replace(":", "/", 1)
        config["model"] = m
    if args.accept_all:
        config["permission_mode"] = "accept-all"
    if args.verbose:
        config["verbose"] = True
    if args.thinking:
        config["thinking"] = True
        config["thinking_mode"] = "extended"
    if args.loud:
        config["thinking"] = True
        config["thinking_mode"] = "loud"
    if args.plan_output:
        config["_plan_output"] = args.plan_output
    if args.session_file:
        config["_session_file"] = args.session_file
    if args.resume_from:
        config["_resume_from"] = args.resume_from
    if args.web_agent_dir:
        config["_web_agent_dir"] = args.web_agent_dir
        os.environ["BOUZECODE_WEB_IPC_DIR"] = args.web_agent_dir
    if args.result_file:
        config["_result_file"] = args.result_file
    if args.resume_pending:
        config["_resume_pending"] = True
    if args.resume_auto:
        config["_resume_auto"] = True

    if not has_api_key(config):
        warn("No API key found. Set ANTHROPIC_API_KEY env var or run: /config anthropic_api_key=YOUR_KEY")

    initial = " ".join(args.prompt) if args.prompt else None
    if args.print_mode and not initial and not args.resume_auto:
        err("--print requires a prompt argument")
        sys.exit(1)

    from .repl import repl
    repl(config, initial_prompt=initial)


if __name__ == "__main__":
    main()
