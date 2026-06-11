# [desc] RunPythonTest tool: runs pytest via uv with auto env loading, parallel support, and project detection [/desc]
"""RunPythonTest tool implementation."""

import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


_PLAYWRIGHT_PLUGIN = '''\
"""Auto-injected by RunPythonTest: force system browser + bypass proxy."""
try:
    from playwright.sync_api import BrowserType
    _orig_launch = BrowserType.launch
    def _patched_launch(self, **kwargs):
        kwargs.setdefault("channel", "msedge")
        args = list(kwargs.get("args") or [])
        if "--no-proxy-server" not in args:
            args.append("--no-proxy-server")
        kwargs["args"] = args
        return _orig_launch(self, **kwargs)
    BrowserType.launch = _patched_launch
except ImportError:
    pass
'''


def _inject_playwright_plugin(env: dict, cmd_parts: list) -> str | None:
    """Inject a pytest plugin that auto-configures Playwright for corporate env.

    Returns tmpdir path (caller cleans up) or None if injection skipped.
    """
    tmpdir = tempfile.mkdtemp(prefix="bz_pw_")
    plugin_path = Path(tmpdir) / "_bz_pw_patch.py"
    plugin_path.write_text(_PLAYWRIGHT_PLUGIN, encoding="utf-8")
    existing = env.get("PYTHONPATH", "")
    sep = ";" if sys.platform == "win32" else ":"
    env["PYTHONPATH"] = f"{tmpdir}{sep}{existing}" if existing else tmpdir
    cmd_parts.extend(["-p", "_bz_pw_patch"])
    return tmpdir

try:
    from tqdm import tqdm as _tqdm
except ImportError:
    _tqdm = None

_COLLECTED_RE = re.compile(r'collected (\d+) items?')
_XDIST_COLLECTED_RE = re.compile(r'\d+ workers? \[(\d+) items?\]')
_XDIST_RESULT_RE = re.compile(r'^\[gw\d+\]\s+(PASSED|FAILED|SKIPPED|ERROR)\s+')
_STANDARD_RESULT_RE = re.compile(r' (PASSED|FAILED|SKIPPED|ERROR)\b')


def _stream_with_progress(proc, timeout: int) -> tuple[list[str], bool]:
    """Read proc stdout line-by-line, display tqdm progress bar on stderr.

    Returns (all_lines, timed_out).
    """
    lines: list[str] = []
    timed_out = False
    total = None
    done = 0
    passed = 0
    failed = 0
    skipped = 0
    bar = None

    def _kill_on_timeout():
        nonlocal timed_out
        timed_out = True
        _kill_proc_tree(proc.pid)

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.start()

    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip('\n\r')
            lines.append(line)

            # Detect total collected
            if total is None:
                m = _COLLECTED_RE.search(line) or _XDIST_COLLECTED_RE.search(line)
                if m:
                    total = int(m.group(1))
                    if _tqdm and total > 0:
                        bar = _tqdm(total=total, desc="pytest", unit="test",
                                    file=sys.stderr, leave=True,
                                    bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}')

            # Detect individual test results
            m = _XDIST_RESULT_RE.match(line) or _STANDARD_RESULT_RE.search(line)
            if m:
                status = m.group(1)
                done += 1
                if status == "PASSED":
                    passed += 1
                elif status == "FAILED":
                    failed += 1
                elif status == "SKIPPED":
                    skipped += 1
                if bar:
                    bar.set_postfix_str(f"✅{passed} ❌{failed} ⏭{skipped}", refresh=False)
                    bar.update(1)

        # stderr merged into stdout via subprocess.STDOUT — no separate read needed

        proc.wait()
    finally:
        timer.cancel()
        if bar:
            bar.close()

    return lines, timed_out


def _find_project_root(target: str | None = None) -> Path:
    """Walk up from target (or cwd) to find the nearest pyproject.toml."""
    start = Path(target).resolve() if target else Path.cwd()
    if start.is_file():
        start = start.parent
    for folder in [start, *start.parents]:
        if (folder / "pyproject.toml").exists():
            return folder
    return Path.cwd()


def _load_env_file(env_path: Path, env: dict[str, str]) -> dict[str, str]:
    """Parse a .env file and merge into env dict (existing keys NOT overwritten)."""
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        env.setdefault(key, value)
    return env


def _get_base_env() -> dict[str, str]:
    """Get environment with user-level vars (Windows registry merge)."""
    env = os.environ.copy()
    try:
        if sys.platform != "win32":
            return env
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    env.setdefault(name, value)
                    i += 1
                except OSError:
                    break
    except Exception:
        pass
    return env


def _kill_proc_tree(pid: int) -> None:
    """Kill process tree (Windows & Unix)."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def run_python_test(
    targets: list[str] | None = None,
    parallel: str = "auto",
    marker: str | None = None,
    keyword: str | None = None,
    timeout: int = 300,
    no_sync: bool = False,
    extra_args: list[str] | None = None,
) -> str:
    """Execute pytest via uv with proper env loading."""
    # Determine project root from first target or cwd
    first_target = targets[0] if targets else None
    project_root = _find_project_root(first_target)

    # Build environment
    env = _get_base_env()
    _load_env_file(project_root / ".env", env)

    # Build pytest command
    cmd_parts = ["uv", "run"]
    if no_sync:
        cmd_parts.append("--no-sync")
    cmd_parts.extend(["--directory", str(project_root), "pytest"])

    # Parallel option
    if parallel == "auto":
        cmd_parts.extend(["-n", "auto"])
    elif parallel != "off":
        # numeric value
        cmd_parts.extend(["-n", str(parallel)])

    # Always verbose
    cmd_parts.append("-v")

    # Marker filter
    if marker:
        cmd_parts.extend(["-m", marker])

    # Keyword filter
    if keyword:
        cmd_parts.extend(["-k", keyword])

    # Extra args
    if extra_args:
        cmd_parts.extend(extra_args)

    # Targets (files/dirs)
    if targets:
        for t in targets:
            # Make paths relative to project_root if they're absolute
            p = Path(t)
            if p.is_absolute():
                try:
                    rel = p.relative_to(project_root)
                    cmd_parts.append(str(rel))
                except ValueError:
                    cmd_parts.append(str(p))
            else:
                cmd_parts.append(t)

    # Inject Playwright plugin for system browser + proxy bypass
    pw_tmpdir = _inject_playwright_plugin(env, cmd_parts)

    # Force unbuffered output so tqdm progress updates in real-time
    env["PYTHONUNBUFFERED"] = "1"

    # Execute with live progress bar
    kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(project_root),
        env=env,
    )
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    cmd_str = " ".join(cmd_parts)
    try:
        proc = subprocess.Popen(cmd_parts, **kwargs)
        lines, timed_out = _stream_with_progress(proc, timeout)

        if timed_out:
            return f"Error: tests timed out after {timeout}s (process killed)\nCommand: {cmd_str}"

        out = "\n".join(lines)
        result = out.strip() or "(no output)"
        header = f"[RunPythonTest] cwd={project_root}\n$ {cmd_str}\n{'─' * 60}\n"
        from .truncation import compact_pytest_output, truncate_tool_output
        compacted = compact_pytest_output(result)
        return header + truncate_tool_output(compacted, "RunPythonTest")

    except FileNotFoundError:
        return (
            f"Error: 'uv' not found. Ensure uv is installed and in PATH.\n"
            f"Command attempted: {cmd_str}"
        )
    except Exception as e:
        return f"Error: {e}\nCommand: {cmd_str}"
