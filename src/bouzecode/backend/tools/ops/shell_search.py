# [desc] Provides shell command execution (PowerShell on win32) and re-exports the glob/grep search helpers. [/desc]
"""Shell execution: the Bash tool, its PowerShell launch and its background twin."""
import base64
import functools
import os
import re
import subprocess
from pathlib import Path

from .shell_command_rewrite import (
    spill_inline_python, spill_note, unwrap_nested_powershell,
)

# Split-out halves, re-exported: importers (tools/__init__.py, registration.py,
# web_v2 runner, tests) address all of these through shell_search.
from .shell_env import (  # noqa: F401
    _get_env_with_user_vars, _merge_user_env, _powershell_exe,
)
from .grep_glob import (  # noqa: F401
    _GREP_BUDGET, _build_grep_summary, _extract_precise_patterns, _glob,
    _grep, _has_rg, _symbol_for_lines,
)


_SAFE_PREFIXES = (
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "printf", "date",
    "which", "type", "env", "printenv", "uname", "whoami", "id",
    "git log", "git status", "git diff", "git show", "git branch",
    "git remote", "git stash list", "git tag",
    "find ", "grep ", "rg ", "ag ", "fd ",
    "python ", "python3 ", "node ", "ruby ", "perl ",
    "pip show", "pip list", "npm list", "cargo metadata",
    "df ", "du ", "free ", "top -bn", "ps ",
    "curl -I", "curl --head",
)


def _is_safe_bash(cmd: str) -> bool:
    c = cmd.strip()
    return any(c.startswith(p) for p in _SAFE_PREFIXES)


def _kill_proc_tree(pid: int):
    import sys as _sys
    if _sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


_BANNED_INLINE_RE = re.compile(
    r'''(?:^|\||\;|\&\&|\|\|)\s*(?:python[23]?|py)\s+-c\s''',
    re.IGNORECASE,
)

_POWERSHELL_CMD_RE = re.compile(
    r'(powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+',
    re.IGNORECASE,
)


def _encode_for_powershell(command: str) -> str:
    """Encode a command as UTF-16LE base64 for PowerShell -EncodedCommand."""
    raw = command.encode("utf-16-le")
    return base64.b64encode(raw).decode("ascii")


# Base64 payload (UTF-16LE) weighs ~2.67x the source; keep the whole argv well
# under the 32767-char CreateProcess cap. Past this, the command body is spilled
# to a temp .ps1 and we EncodedCommand only a tiny stub that launches it.
_ENCODED_LIMIT = 8000


def _write_temp_ps1(command: str) -> str:
    """Write `command` to a temp .ps1 and return its path.

    UTF-8 *with BOM* is mandatory: PowerShell 5.1 reads a BOM-less .ps1 as ANSI,
    which turns accented text into mojibake."""
    import tempfile
    fd, path = tempfile.mkstemp(prefix="temp_bash_", suffix=".ps1")
    os.close(fd)
    Path(path).write_text(command, encoding="utf-8-sig")
    return path


def _build_popen_command(command: str):
    """Return (popen_cmd, shell, temp_path) ready for subprocess.Popen.

    win32: always PowerShell -EncodedCommand, passed as an argv list (shell=False,
    so no cmd.exe 8191-char cap). A large body is spilled to a temp .ps1 and the
    encoded payload becomes a tiny `& '<file>'` stub — so the cmdline stays small
    whatever the script size, and the launch itself is still EncodedCommand.
    Other platforms: run via the shell, injecting -NonInteractive into explicit
    powershell calls. temp_path (or None) is returned so the caller can clean up.

    A command that is ITSELF a redundant `powershell -Command "..."` wrapper is
    unwrapped first (win32 only — elsewhere the outer shell is not PowerShell, so
    the wrapper is doing real work): we are already in PowerShell, and the extra
    shell interpolates the body's variables away. See unwrap_nested_powershell
    for the exact boundary. Each unwrap strips the host token, so the loop ends."""
    import sys as _sys
    if _sys.platform == "win32":
        while (unwrapped := unwrap_nested_powershell(command)) is not None:
            command = unwrapped
        encoded = _encode_for_powershell(command)
        temp_path = None
        if len(encoded) > _ENCODED_LIMIT:
            temp_path = _write_temp_ps1(command)
            encoded = _encode_for_powershell(f"& '{temp_path}'; exit $LASTEXITCODE")
        argv = [_powershell_exe(), "-NonInteractive", "-EncodedCommand", encoded]
        return argv, False, temp_path
    if _POWERSHELL_CMD_RE.search(command) and '-noninteractive' not in command.lower():
        command = re.sub(
            r'(powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+(-Command)',
            r'\1 -NonInteractive \2',
            command,
            flags=re.IGNORECASE,
        )
    return command, True, None


_CLIXML_S_RE = re.compile(r"<S(?:\s[^>]*)?>(.*?)</S>", re.DOTALL)
_CLIXML_XESC_RE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def _decode_clixml_text(s: str) -> str:
    s = _CLIXML_XESC_RE.sub(lambda m: chr(int(m.group(1), 16)), s)
    for ent, ch in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                    ("&apos;", "'"), ("&amp;", "&")):
        s = s.replace(ent, ch)
    return s


def _strip_clixml(stderr: str) -> str:
    """Drop PowerShell's `#< CLIXML <Objs>...</Objs>` envelope (module-load progress
    noise) from a native exe's stderr, but keep the genuine error text: a native
    exe's own stderr is interleaved as RAW lines after the `#< CLIXML` header
    (not wrapped in tags), while PowerShell records sit in `<S>`/`<Objs>` tags."""
    if not stderr or "#< CLIXML" not in stderr[:64]:
        return stderr
    body = stderr.split("\n", 1)[1] if "\n" in stderr else ""
    s_lines = "".join(_decode_clixml_text(seg) for seg in _CLIXML_S_RE.findall(body))
    raw = re.sub(r"<Objs\b.*?</Objs>", "", body, flags=re.DOTALL)  # drop progress envelope
    raw = _CLIXML_S_RE.sub("", raw)                                # already recovered above
    parts = [p for p in (raw.strip(), s_lines.strip()) if p]
    return "\n".join(parts)


_DEFAULT_BASH_TIMEOUT = 180


def _render_deferred_note(queue: list) -> str:
    """Compact human-readable render of the deferred queue (first 10 lines each)."""
    lines = [f"File differee (executee a la cloture) - {len(queue)} commandes:"]
    for i, item in enumerate(queue, 1):
        cmd = item.get("command", "")
        head = cmd.splitlines()[:10]
        lines.append(f"#{i} (timeout={item.get('timeout')}s):")
        lines.extend(f"  {ln}" for ln in head)
    return "\n".join(lines)


def bash_handler(params: dict, config: dict) -> str:
    """Tool handler for Bash. Branches to background exec or the deferred queue."""
    command = params["command"]
    timeout = params.get("timeout", _DEFAULT_BASH_TIMEOUT)
    if params.get("background"):
        from .bash_bg import start_background
        return start_background(command)
    if params.get("deferred"):
        from ...context_manager.state import resolve_context_state
        context_state = resolve_context_state(config)
        if context_state is not None:
            if not getattr(context_state, "deferred_queue", None):
                context_state.deferred_queue = []
            context_state.deferred_queue.append({"command": command, "timeout": timeout})
            context_state.notes["deferred"] = _render_deferred_note(context_state.deferred_queue)
            return f"Bash deferred #{len(context_state.deferred_queue)} saved (runs at close)"
    return _bash(command, timeout)


def _substitute_scratch_paths(command: str) -> str:
    """Replace any registered scratch LOGICAL path in the command by its REAL path.

    Bash/Glob/Grep never see the logical path a temp file was written under
    (temp=True routes writes to a scratch dir outside the worktree). So before
    running a shell command we swap every registered logical path for its real
    on-disk path. Matching is token-bounded (not naive substring) so that a
    logical name is only replaced when it stands alone in the command
    (e.g. `python temp_x.py`, `> temp_out.txt`), never mid-word.
    """
    try:
        from .scratch import all_temp_paths
        pairs = all_temp_paths()
    except Exception:
        return command
    if not pairs:
        return command
    import re as _re
    # Longest logical paths first so a longer path is not shadowed by a prefix.
    for logical, real in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
        if not logical:
            continue
        pattern = r"(?<![\w./\\-])" + _re.escape(logical) + r"(?![\w./\\-])"
        command = _re.sub(pattern, real.replace("\\", "\\\\"), command)
    return command


INLINE_PYTHON_REFUSAL = (
    "BLOCKED: `python -c` is banned. Inline Python is fragile "
    "and wastes tokens on quoting issues, and here the code could not be "
    "extracted from its quotes to be spilled into a file automatically.\n"
    "Instead: Write a temp_*.py file, Bash `python temp_*.py`, "
    "then delete it (all in one turn with depends_on)."
)


def spill_or_refuse_inline_python(command: str) -> tuple[str, str]:
    """Return (command to run, note to prepend) for a command holding `python -c`.

    Inline Python is not refused any more: the code is written to a temp_*.py
    scratch file and that file is run, which is exactly the recipe the old
    refusal asked the agent to perform by hand. Refusing survives only when the
    inline code cannot be extracted losslessly. An empty command means refused.
    """
    if not _BANNED_INLINE_RE.search(command):
        return command, ""
    spilled = spill_inline_python(command)
    if spilled is None:
        return "", INLINE_PYTHON_REFUSAL
    rewritten, files = spilled
    return rewritten, spill_note(files) + "\n"


def _bash(command: str, timeout: int = _DEFAULT_BASH_TIMEOUT) -> str:
    import contextlib
    import sys as _sys
    original_command = command  # win32: spilled/encoded below, keep raw for checks
    command, note = spill_or_refuse_inline_python(command)
    if not command:
        return note
    command = _substitute_scratch_paths(command)
    popen_cmd, shell, temp_path = _build_popen_command(command)
    kwargs = dict(
        shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=os.getcwd(),
        env=_get_env_with_user_vars(),
    )
    if _sys.platform != "win32":
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(popen_cmd, **kwargs)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            proc.wait()
            # Ne recommande RunPythonTest que s'il est RÉELLEMENT activé pour cet agent :
            # conseiller un outil refusé derrière coûte un tour entier pour rien.
            from ...core.tool_registry import is_enabled
            pytest_hint = (" Pour pytest, préfère RunPythonTest (timeout long dédié)."
                           if is_enabled("RunPythonTest") else "")
            return note + (
                f"Error: timed out after {timeout}s (process killed). "
                f"Le param `timeout` n'est pas capé — relance avec timeout={timeout * 4} "
                f"si la commande est légitimement longue (suite de tests, build, install)."
                f"{pytest_hint}"
            )
        out = stdout
        stderr = _strip_clixml(stderr)
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr
        if rc == 0 and not stdout.strip() and not stderr.strip():
            return note + (
                "⚠️ sortie vide — probable pipe/quoting PowerShell, vérifie ta commande.\n"
                "Astuce: redirige la sortie vers un fichier puis lis-le, "
                "ou utilise RunPythonTest pour lancer les tests."
            )
        result = out.strip() or "(no output)"
        from .truncation import truncate_tool_output, compact_pytest_output
        if "pytest" in original_command and result.count("\n") > 150:
            result = compact_pytest_output(result)
        # note first, and OUTSIDE truncation: where the spilled script lives must
        # survive a truncated output — that is when it matters most.
        return note + truncate_tool_output(result, "Bash")
    except Exception as e:
        return note + f"Error: {e}"
    finally:
        if temp_path:
            with contextlib.suppress(OSError):
                os.remove(temp_path)
