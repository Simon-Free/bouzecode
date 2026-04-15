#!/usr/bin/env python3
# [desc] CLI entry point and re-exports for bouzécode, a minimal Python implementation of Claude Code. [/desc]
"""
bouzécode (based on cheetahclaws) — Minimal Python implementation of Claude Code.

Usage:
  python bouzecode.py [options] [prompt]

Options:
  -p, --print          Non-interactive: run prompt and exit (also --print-output)
  -m, --model MODEL    Override model
  --accept-all         Never ask permission (dangerous)
  --verbose            Show thinking + token counts
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
  /thinking   Toggle extended thinking
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
  /voice            Record voice input, transcribe, and submit
  /voice status     Show available recording and STT backends
  /voice lang <code>  Set STT language (e.g. zh, en, ja — default: auto)
  /proactive [dur]  Background sentinel polling (e.g. /proactive 5m)
  /proactive off    Disable proactive polling
  /cloudsave setup <token>   Configure GitHub token for cloud sync
  /cloudsave        Upload current session to GitHub Gist
  /cloudsave push [desc]     Upload with optional description
  /cloudsave auto on|off     Toggle auto-upload on exit
  /cloudsave list   List your bouzecode Gists
  /cloudsave load <gist_id>  Download and load a session from Gist
  /exit /quit Exit
"""
from __future__ import annotations

import argparse
import os
import sys

if sys.platform == "win32":
    os.system("")  # Enable ANSI escape codes on Windows CMD

VERSION = "3.05.5"

# Backward-compat re-exports — some tools/tests still `from bouzecode import X`.
from ui.ansi import C, clr, info, ok, warn, err
from ui.rendering import (
    console, _RICH, _accumulated_text, _current_live, _live_overflow,
    _overflow_lines_buf, stream_text, stream_thinking, flush_response,
)
from ui.spinner import _start_tool_spinner, _stop_tool_spinner
from ui.tool_display import (
    print_tool_start, print_tool_end, render_diff, _last_diffs, _fmt_duration,
)
from commands import (
    COMMANDS, handle_slash, setup_readline,
    save_latest, _build_session_data, _tg_send,
)
from commands.misc import cmd_init, cmd_export, cmd_copy, cmd_diff
from commands.diagnostics import cmd_status
from tools import ask_input_interactive, _tg_thread_local, _is_in_tg_turn


def strip_unpaired_surrogates(raw: str) -> str:
    """Windows clipboard paste can leave unpaired UTF-16 surrogates that the
    Anthropic SDK cannot encode to UTF-8. Recombine valid high+low pairs via
    UTF-16 round-trip, then drop any orphans via UTF-8 round-trip."""
    recombined = raw.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return recombined.encode("utf-8", "replace").decode("utf-8", "replace")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bouzecode",
        description="bouz\u00e9code (based on cheetahclaws) \u2014 minimal Python Claude Code implementation",
        add_help=False,
    )
    parser.add_argument("prompt", nargs="*", help="Initial prompt (non-interactive)")
    parser.add_argument("-p", "--print", "--print-output",
                        dest="print_mode", action="store_true",
                        help="Non-interactive mode: run prompt and exit")
    parser.add_argument("-m", "--model", help="Override model")
    parser.add_argument("--accept-all", action="store_true",
                        help="Never ask permission (accept all operations)")
    parser.add_argument("--verbose", action="store_true", help="Show thinking + token counts")
    parser.add_argument("--thinking", action="store_true", help="Enable extended thinking")
    parser.add_argument("--plan-output", help="Save final response as markdown to this file path")
    parser.add_argument("--session-file", help="Save session state (messages) after each tool round")
    parser.add_argument("--resume-from", help="Resume from a saved session file (restore messages)")
    parser.add_argument("--web-agent-dir", help="Run as a BouzéGUI web agent: IPC dir for state/followup/answer/cancel")
    parser.add_argument("--resume-pending", action="store_true",
                        help="Resume a paused turn (AskUserQuestion): load <session>.pending.json, inject the prompt as answer, finish remaining tool_calls")
    parser.add_argument("--version", action="store_true", help="Print version")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")

    args = parser.parse_args()

    if args.version:
        print(f"bouz\u00e9code v{VERSION}")
        sys.exit(0)
    if args.help:
        print(__doc__)
        sys.exit(0)

    from config import load_config, has_api_key
    from providers import detect_provider, PROVIDERS

    config = load_config()

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
    if args.plan_output:
        config["_plan_output"] = args.plan_output
    if args.session_file:
        config["_session_file"] = args.session_file
    if args.resume_from:
        config["_resume_from"] = args.resume_from
    if args.web_agent_dir:
        config["_web_agent_dir"] = args.web_agent_dir
        os.environ["BOUZECODE_WEB_IPC_DIR"] = args.web_agent_dir
    if args.resume_pending:
        config["_resume_pending"] = True

    if not has_api_key(config):
        warn("No API key found. Set ANTHROPIC_API_KEY env var or run: /config anthropic_api_key=YOUR_KEY")

    initial = " ".join(args.prompt) if args.prompt else None
    if args.print_mode and not initial:
        err("--print requires a prompt argument")
        sys.exit(1)

    from repl import repl
    repl(config, initial_prompt=initial)


if __name__ == "__main__":
    main()
