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
from pathlib import Path
from .ansi import C, clr, info, ok, warn, err
from .messages import msg
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
    print(f"\033[33m⚠ {msg('ripgrep.missing')}\033[0m", flush=True)
    try:
        import urllib.request, zipfile, tempfile
        version = "14.1.1"
        url = f"https://github.com/BurntSushi/ripgrep/releases/download/{version}/ripgrep-{version}-x86_64-pc-windows-msvc.zip"
        os.makedirs(local_bin, exist_ok=True)
        zip_path = os.path.join(tempfile.gettempdir(), "ripgrep.zip")
        print(msg("ripgrep.downloading", version=version), flush=True)
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
        print(f"\033[32m✓ {msg('ripgrep.installed')}\033[0m", flush=True)
    except Exception as exc:
        releases_url = "https://github.com/BurntSushi/ripgrep/releases"
        print(
            f"\033[31m✗ {msg('ripgrep.install_failed', error=exc)}\033[0m\n"
            + msg("ripgrep.download_manually", url=releases_url),
            flush=True,
        )


def _find_powershell_dir() -> str | None:
    """Return a directory containing powershell.exe/pwsh.exe, or None.

    Probes the canonical Windows PowerShell 5.1 location (under %SystemRoot%)
    first, then a PowerShell 7 install, so a PATH stripped of these still
    resolves."""
    candidates = [
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                     "System32", "WindowsPowerShell", "v1.0"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "PowerShell", "7"),
    ]
    for directory in candidates:
        for exe in ("powershell.exe", "pwsh.exe"):
            if os.path.isfile(os.path.join(directory, exe)):
                return directory
    return None


def _planned_user_path(directory: str, current_user_path: str) -> str | None:
    """The user PATH to persist so `directory` is on it, or None to skip.

    Skips (None) when `directory` is already present, or when prepending it would
    exceed setx's 1024-char truncation limit — writing past that silently
    corrupts PATH. Pure: no I/O, so the persistence decision stays testable."""
    existing = [p.strip().lower() for p in current_user_path.split(os.pathsep) if p.strip()]
    if directory.lower() in existing:
        return None
    new_user_path = directory + os.pathsep + current_user_path if current_user_path else directory
    return new_user_path if len(new_user_path) <= 1024 else None


def _persist_user_path_entry(directory: str) -> None:
    """Prepend `directory` to the *user* PATH permanently via setx.

    Reads HKCU\\Environment Path (NOT the merged process PATH) so the system
    PATH is never duplicated into the user PATH."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            user_path, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        user_path = ""
    new_user_path = _planned_user_path(directory, user_path)
    if new_user_path is None:
        if len(directory + os.pathsep + user_path) > 1024:
            print(msg("path.too_long_for_setx"), file=sys.stderr, flush=True)
        return
    import subprocess
    subprocess.run(["setx", "PATH", new_user_path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(msg("path.persisted"), file=sys.stderr, flush=True)


def _ensure_powershell_on_path() -> None:
    """On Windows, guarantee `powershell` resolves on PATH.

    Every Bash tool command is rewritten to `powershell -EncodedCommand …`
    (see shell_search._bash), so a PATH missing the WindowsPowerShell directory
    breaks every shell command with `'powershell' n'est pas reconnu`. Repair it
    in-process for this session, and persist via setx for future ones."""
    if sys.platform != "win32":
        return
    import shutil
    if shutil.which("powershell") or shutil.which("pwsh"):
        return
    ps_dir = _find_powershell_dir()
    if ps_dir is None:
        print(f"\033[31m✗ {msg('powershell.not_found')}\033[0m",
              file=sys.stderr, flush=True)
        return
    os.environ["PATH"] = ps_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"\033[33m⚠ {msg('powershell.added_to_path', directory=ps_dir)}\033[0m",
          file=sys.stderr, flush=True)
    _persist_user_path_entry(ps_dir)


def _load_repo_dotenv() -> None:
    """Load the bouzecode repo's own .env into os.environ so the agent works no
    matter how it is launched (bare exe, PATH shim, or the full .ps1 launcher).

    Targets the .env next to the *package source* (editable install), not the
    current project's cwd. Never overrides a variable already set, so the
    launcher and any explicit environment keep priority. Maps
    ANTHROPIC_AUTH_TOKEN onto ANTHROPIC_API_KEY when only the former is given,
    as some gateways issue the credential under that name.
    """
    try:
        # .../<repo>/src/bouzecode/ui/cli.py -> parents[3] == <repo>
        repo_root = Path(__file__).resolve().parents[3]
    except IndexError:
        return
    env_file = repo_root / ".env"
    if not env_file.exists():
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
    if "ANTHROPIC_API_KEY" not in os.environ and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]


def apply_profile_skills(config: dict, profile_name: str) -> None:
    """Preload a `--profile` agent's declared skills into the prompt — the sanctioned path
    (render_profile_skills), same as /agent (agent_switch) and the manager. Without this,
    web-dispatched `--profile` agents got the persona but NONE of their declared skills, so
    a profile that lists e.g. conversation-download never surfaced it (missed at turn 1)."""
    from bouzecode.backend.profiles import resolve_agent_profile
    profile = resolve_agent_profile(profile_name)
    if profile and profile.skills:
        config["_profile_skills"] = list(profile.skills)


def apply_profile_hooks(profile_name: str) -> None:
    """Wire a `--profile` agent's declared `hooks` into this process's event
    registry — MIRROR of apply_profile_tools/apply_profile_skills. Each name is
    resolved against the unified named-hook catalog (bouzecode builtins + plugin
    HOOK_DEFS) and registered under its event. A profile with no `hooks:` wires
    nothing (general-purpose/default/manager stay hook-free)."""
    from bouzecode.backend.profiles import resolve_agent_profile
    from bouzecode.backend.agent.hooks import pipeline
    profile = resolve_agent_profile(profile_name)
    if not (profile and profile.hooks):
        return
    for name in profile.hooks:
        pipeline.register_named(name)


def apply_profile_plan_mode(config: dict, profile_name: str) -> None:
    """A profile with `plan_mode: false` (dispatcher/manager) opts OUT of the
    WritePlan auto-validator and the plan-validation pause: it never writes a
    validated plan nor blocks on `awaiting_plan_validation`."""
    from bouzecode.backend.profiles import resolve_agent_profile
    profile = resolve_agent_profile(profile_name)
    if profile is not None and getattr(profile, "plan_mode", True) is False:
        config["_plan_mode_disabled"] = True


def apply_profile_recap(config: dict, profile_name: str) -> None:
    """A profile with `require_recap: true` (coder) makes the close-gate
    DÉTERMINISTE refuse a FinalAnswer without a complete structured recap object
    (symptoms/explanation/tests/changes). MIRROR of manager._apply_profile — without
    this, the `--profile` CLI path (used by the web_v2 runner to spawn coders) applied
    the recap INSTRUCTION (prompt) but never the ENFORCEMENT, so coders closed without
    a recap and every GET /recap came back empty (recap_missing).

    EXEMPTION : un validateur/merger porte le MÊME profil que le codeur (coder) mais
    NE livre PAS de récap — il rend `VERDICT: OK|KO`. Sans cette garde il était refusé en
    boucle par le gate puis FABRIQUAIT un faux récap de codeur pour pouvoir clôturer. Le
    run_kind arrive via l'env BOUZECODE_RUN_KIND (runner.py) ; seul `work` exige un récap."""
    import os
    if (os.environ.get("BOUZECODE_RUN_KIND") or "work") != "work":
        return
    from bouzecode.backend.profiles import resolve_agent_profile
    profile = resolve_agent_profile(profile_name)
    if profile is not None and getattr(profile, "require_recap", False):
        config["require_recap"] = True
        config["recap_expects_object"] = True
        config["recap_coding"] = True


def apply_profile_tools(profile_name: str) -> None:
    """Apply a `--profile` agent's `tools` list as a true WHITELIST of work tools.

    tools/registration.py disables every optional tool at import (`_DEFAULT_ENABLED`
    = framework + default work tools), so Agent / ListAgentTypes are off by default.
    When a profile declares a NON-EMPTY `tools` list we:
      - keep the framework tools (`FRAMEWORK_ALWAYS_ON`) always enabled — they carry
        the harness discipline and can never be stripped;
      - enable exactly the declared work tools (e.g. the manager's Agent/ListAgentTypes);
      - DISABLE every other work tool — notably Edit/Write when the profile omits them,
        so a read-only manager genuinely cannot edit files and must delegate via Agent.
    An empty / missing `tools` list means "no restriction": the default whitelist is
    left untouched (general-purpose, meta-agent keep full Edit/Write access).

    WHICH tools that resolves to is decided by `enabled_tools_for_profile` — the same
    function the prompt/registry conformity test reads, so what an agent is told it
    has and what it may call can never drift apart."""
    from bouzecode.backend.tools.registration import enabled_tools_for_profile
    from bouzecode.backend.profiles import resolve_agent_profile
    from bouzecode.backend.core.tool_registry import enable_tool, disable_tool, _registry

    profile = resolve_agent_profile(profile_name)
    if not (profile and profile.tools):
        return
    allowed = enabled_tools_for_profile(profile_name)
    for tool_name in list(_registry.keys()):
        if tool_name in allowed:
            enable_tool(tool_name)
        else:
            disable_tool(tool_name)


def main() -> None:
    # Self-load the repo .env early so the API key / base_url are present before
    # any config load or API call, regardless of launch method.
    _load_repo_dotenv()

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
    parser.add_argument("--resume-deferred", default="",
                        help="Resume after a deferred check failed: load <session>.deferred.json, inject the error log as a SYSTEM message, and re-run a turn")
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

    _ensure_powershell_on_path()
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

    from bouzecode.backend.core.config import load_config
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
    # Extra dirs persisted via the UI / config.json (survive across runs)
    from bouzecode.backend.core.paths import register_persisted_extra_dirs
    register_persisted_extra_dirs()

    if args.monitor:
        args.profile = "monitor"
    if args.profile:
        # Pre-empts task classification (loop.py only classifies when the key is absent).
        config["_task_classification_result"] = args.profile
        apply_profile_skills(config, args.profile)
        apply_profile_tools(args.profile)
        apply_profile_hooks(args.profile)
        apply_profile_plan_mode(config, args.profile)
        apply_profile_recap(config, args.profile)
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
        # Web-dispatched agents must close via an explicit FinalAnswer (nudge
        # cap 4, then force-close) instead of the legacy meta-only/text close,
        # which prematurely killed agents still reading via Snippet.
        config["close_requires_final_answer"] = True
    if args.result_file:
        config["_result_file"] = args.result_file
    if args.resume_pending:
        config["_resume_pending"] = True
    if args.resume_auto:
        config["_resume_auto"] = True
    if args.resume_deferred:
        config["_resume_deferred"] = args.resume_deferred

    # Takes every provider into account: a user with only OPENROUTER_KEY used to
    # be told "No API key found", which is false — what is missing is a model
    # that OpenRouter serves.
    from bouzecode.backend.agent.providers.missing_key import startup_key_warning
    _key_warning = startup_key_warning(config["model"], config)
    if _key_warning:
        warn(_key_warning)

    initial = " ".join(args.prompt) if args.prompt else None
    # --resume-deferred (like --resume-auto) carries no positional prompt: the prompt is
    # synthesized in repl from the failed check's error log. Without this exemption the
    # web runner's deferred-failure respawn (`-p --resume-deferred <err>`) died here on
    # every retry, so the model never saw the error and the drain looped forever.
    if args.print_mode and not initial and not args.resume_auto and not args.resume_deferred:
        err("--print requires a prompt argument")
        sys.exit(1)

    from .repl import repl
    from bouzecode.backend.agent.providers.missing_key import MissingApiKeyError
    try:
        repl(config, initial_prompt=initial)
    except MissingApiKeyError as exc:
        # A configuration error, not a crash: print the diagnosis, skip the
        # 25-line traceback that used to bury it.
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
