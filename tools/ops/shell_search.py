# [desc] Provides shell command execution, file glob, and grep search utility functions. [/desc]
"""Shell execution, glob, and grep operations."""
import functools
import os
import re
import subprocess
from pathlib import Path

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


def _bash(command: str, timeout: int = 30) -> str:
    import sys as _sys
    if _sys.platform == "win32" and _BANNED_INLINE_RE.search(command):
        return (
            "BLOCKED: `python -c` is banned on Windows \u2014 multi-line code and "
            "quotes break silently through the shell layer.\n"
            "Instead: use the Write tool to create a temp_*.py file, then "
            "Bash `python temp_*.py` (or `powershell.exe -Command '& python temp_*.py'`)."
        )
    kwargs = dict(
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=os.getcwd(),
    )
    if _sys.platform != "win32":
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(command, **kwargs)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            proc.wait()
            return f"Error: timed out after {timeout}s (process killed)"
        out = stdout
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr
        return out.strip() or "(no output)"
    except Exception as e:
        return f"Error: {e}"


@functools.lru_cache(maxsize=1)
def _has_rg() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _glob(pattern: str, path: str = None) -> str:
    base = Path(path) if path else Path.cwd()
    if _has_rg():
        cmd = ["rg", "--files", "--no-require-git", "-g", pattern, str(base)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30)
            matches = sorted(r.stdout.strip().splitlines()) if r.stdout.strip() else []
        except Exception as e:
            return f"Error: {e}"
    else:
        try:
            matches = sorted(str(m) for m in base.glob(pattern))
        except Exception as e:
            return f"Error: {e}"
    if not matches:
        return "No files matched"
    return "\n".join(matches[:500])


def _grep(pattern: str, path: str = None, glob: str = None,
          output_mode: str = "content",
          case_insensitive: bool = False, context: int = 0) -> str:
    if not path:
        return (
            "Error: `path` is required. Scope the search to a specific "
            "subdirectory \u2014 scanning cwd recursively is forbidden on large "
            "repos (walks .venv, node_modules, etc. and hides real results)."
        )
    use_rg = _has_rg()
    cmd = ["rg" if use_rg else "grep", "--no-heading"]
    if case_insensitive:
        cmd.append("-i")
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    else:
        cmd.append("-n")
        if context:
            cmd += ["-C", str(context)]
    if glob:
        cmd += (["--glob", glob] if use_rg else ["--include", glob])
    cmd.append(pattern)
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        out = r.stdout.strip()
        if out:
            return out[:20000]
        return f"No matches found for pattern {pattern!r} in {path}"
    except Exception as e:
        return f"Error: {e}"
