# [desc] Provides shell command execution, file glob, and grep search utility functions. [/desc]
"""Shell execution, glob, and grep operations."""
import base64
import functools
import os
import re
import subprocess
from pathlib import Path

_GREP_BUDGET = 1000  # max chars before switching to summary mode


@functools.lru_cache(maxsize=1)
def _get_env_with_user_vars() -> dict[str, str]:
    """On Windows, merge user-level env vars from registry into process env.

    This ensures vars set at user level (HKCU\\Environment) are available
    even if the parent process was started before they were defined.
    """
    env = os.environ.copy()
    try:
        import sys as _sys
        if _sys.platform != "win32":
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


def _bash(command: str, timeout: int = 30) -> str:
    import sys as _sys
    original_command = command  # la version win32 est réécrite en -EncodedCommand
    if _BANNED_INLINE_RE.search(command):
        return (
            "BLOCKED: `python -c` is banned. Inline Python is fragile "
            "and wastes tokens on quoting issues.\n"
            "Instead: Write a temp_*.py file, Bash `python temp_*.py`, "
            "then delete it (all in one turn with depends_on)."
        )
    if _sys.platform == "win32":
        # On Windows, encode ALL commands via PowerShell -EncodedCommand
        # This avoids all escaping issues with cmd.exe
        encoded = _encode_for_powershell(command)
        command = f"powershell -NonInteractive -EncodedCommand {encoded}"
    else:
        # On non-Windows, inject -NonInteractive for explicit PowerShell calls
        if _POWERSHELL_CMD_RE.search(command) and '-noninteractive' not in command.lower():
            command = re.sub(
                r'(powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+(-Command)',
                r'\1 -NonInteractive \2',
                command,
                flags=re.IGNORECASE,
            )
    kwargs = dict(
        shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=os.getcwd(),
        env=_get_env_with_user_vars(),
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
            return (
                f"Error: timed out after {timeout}s (process killed). "
                f"Le param `timeout` n'est pas capé — relance avec timeout={timeout * 4} "
                f"si la commande est légitimement longue (suite de tests, build, install). "
                f"Pour pytest, préfère RunPythonTest (timeout long dédié)."
            )
        out = stdout
        stderr = _strip_clixml(stderr)
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr
        result = out.strip() or "(no output)"
        from .truncation import truncate_tool_output, compact_pytest_output
        if "pytest" in original_command and result.count("\n") > 150:
            result = compact_pytest_output(result)
        return truncate_tool_output(result, "Bash")
    except Exception as e:
        return f"Error: {e}"


@functools.lru_cache(maxsize=1)
def _has_rg() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _glob(pattern: str, path: str = None,
          ignore_gitignore: bool = True, include_patterns: list = None) -> str:
    base = Path(path) if path else Path.cwd()
    if _has_rg():
        cmd = ["rg", "--files", "--no-require-git", "-g", pattern, str(base)]
        if not ignore_gitignore:
            cmd.insert(2, "--no-ignore")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30)
            matches = sorted(r.stdout.strip().splitlines()) if r.stdout.strip() else []
        except Exception as e:
            return f"Error: {e}"
        # Second pass for include_patterns (files normally ignored by .gitignore)
        if ignore_gitignore and include_patterns:
            extra = set()
            for ip in include_patterns:
                cmd2 = ["rg", "--files", "--no-require-git", "--no-ignore",
                         "-g", ip, str(base)]
                try:
                    r2 = subprocess.run(cmd2, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=30)
                    if r2.stdout.strip():
                        # Filter: only keep files that also match the original glob pattern
                        from fnmatch import fnmatch
                        for f in r2.stdout.strip().splitlines():
                            if fnmatch(Path(f).name, pattern.lstrip("**/").lstrip("/")):
                                extra.add(f)
                            elif fnmatch(f, pattern):
                                extra.add(f)
                except Exception:
                    pass
            if extra:
                matches = sorted(set(matches) | extra)
    else:
        try:
            matches = sorted(str(m) for m in base.glob(pattern))
        except Exception as e:
            return f"Error: {e}"
    if not matches:
        return "No files matched"
    return "\n".join(matches[:500])


def _extract_precise_patterns(matches: list, pattern: str) -> list:
    """Find longer compound identifiers containing the search term."""
    pat_lower = pattern.lower()
    word_re = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]{2,}')
    from collections import Counter
    compounds = Counter()
    for m in matches:
        for word in word_re.findall(m[2]):
            wl = word.lower()
            if pat_lower in wl and wl != pat_lower and len(word) > len(pattern) + 2:
                compounds[word] += 1
    return [w for w, _ in compounds.most_common(8)]


def _symbol_for_lines(filepath: str, line_nums: list) -> dict:
    """Map line numbers to enclosing def/class symbol (py/js only)."""
    if not any(filepath.endswith(ext) for ext in (".py", ".js", ".ts")):
        return {}
    try:
        cmd = ["rg", "-n", r"^\s*(def |async def |class |function )", filepath]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if not r.stdout.strip():
            return {}
        symbols = []
        for ln in r.stdout.strip().splitlines():
            p = ln.split(":", 1)
            if len(p) >= 2:
                symbols.append((int(p[0]), p[1].strip()))
        result = {}
        for ml in line_nums:
            enclosing = None
            for sline, stext in symbols:
                if sline <= ml:
                    enclosing = stext
                else:
                    break
            if enclosing:
                nm = re.search(r'(?:def|class|function)\s+(\w+)', enclosing)
                result[ml] = nm.group(1) if nm else enclosing[:30]
        return result
    except Exception:
        return {}


def _build_grep_summary(raw: str, pattern: str, path: str) -> str:
    """Compact summary when grep output exceeds budget."""
    if len(raw) <= _GREP_BUDGET:
        return raw
    lines = raw.splitlines()
    matches = []
    # Non-greedy path so the first ":<lineno>:" wins — this keeps a Windows
    # drive-letter colon (C:\...) inside the path instead of mis-splitting on it.
    _line_re = re.compile(r"^(.*?):(\d+):(.*)$")
    for ln in lines:
        m = _line_re.match(ln)
        if m:
            matches.append((m.group(1), int(m.group(2)), m.group(3).strip()))
    if not matches:
        return raw[:_GREP_BUDGET]

    from collections import defaultdict
    by_dir = defaultdict(lambda: {"files": set(), "count": 0})
    by_file = defaultdict(list)
    for fp, lnum, content in matches:
        d = os.path.dirname(fp) or "."
        by_dir[d]["files"].add(fp)
        by_dir[d]["count"] += 1
        by_file[fp].append((lnum, content))

    precise = _extract_precise_patterns(matches, pattern)

    # Symbol context for top 3 files
    top_files = sorted(by_file.items(), key=lambda x: -len(x[1]))[:5]
    sym_maps = {}
    for fp, fmatches in top_files[:3]:
        sym_maps[fp] = _symbol_for_lines(fp, [ln for ln, _ in fmatches])

    out = [f"Grep overflow: {len(matches)} matches in {len(by_file)} files"]
    out.append("\nBy directory:")
    for d, info in sorted(by_dir.items(), key=lambda x: -x[1]["count"])[:5]:
        out.append(f"  {d:<45} {len(info['files'])}f {info['count']}m")
    if len(by_dir) > 5:
        out.append(f"  ({len(by_dir) - 5} more dirs)")

    out.append("\nTop files:")
    for fp, fmatches in top_files:
        syms = sym_maps.get(fp, {})
        sym_names = sorted(set(syms.values()))
        sym_str = f" [{', '.join(sym_names[:4])}]" if sym_names else ""
        out.append(f"  {fp}  ({len(fmatches)}m){sym_str}")

    out.append("\nPreview:")
    for fp, lnum, content in matches[:3]:
        syms = sym_maps.get(fp, {})
        sym = f" in {syms[lnum]}" if lnum in syms else ""
        out.append(f"  {fp}:{lnum}{sym}: {content[:80]}")

    if precise:
        out.append(f"\nPrecise patterns: {', '.join(precise)}")

    top_dir = sorted(by_dir.items(), key=lambda x: -x[1]["count"])[0][0]
    out.append(f"\nRefine:")
    out.append(f'  Grep(pattern="{pattern}", path="{top_dir}")')
    if precise:
        out.append(f'  Grep(pattern="{precise[0]}", path="{path}")')

    return "\n".join(out)


def _grep(pattern: str, path: str = None, glob: str = None,
          output_mode: str = "content",
          case_insensitive: bool = False, context: int = 0,
          ignore_gitignore: bool = True, include_patterns: list = None) -> str:
    if not path:
        path = str(Path.cwd())
    use_rg = _has_rg()
    cmd = ["rg" if use_rg else "grep", "--no-heading"]
    if use_rg:
        cmd.append("--no-require-git")
        if not ignore_gitignore:
            cmd.append("--no-ignore")
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
    except Exception as e:
        return f"Error: {e}"

    # Second pass for include_patterns (search in files normally ignored)
    extra_out = ""
    if use_rg and ignore_gitignore and include_patterns:
        cmd2 = ["rg", "--no-heading", "--no-require-git", "--no-ignore"]
        if case_insensitive:
            cmd2.append("-i")
        if output_mode == "files_with_matches":
            cmd2.append("-l")
        elif output_mode == "count":
            cmd2.append("-c")
        else:
            cmd2.append("-n")
            if context:
                cmd2 += ["-C", str(context)]
        for ip in include_patterns:
            cmd2 += ["--glob", ip]
        if glob:
            cmd2 += ["--glob", glob]
        cmd2.append(pattern)
        cmd2.append(path)
        try:
            r2 = subprocess.run(cmd2, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
            extra_out = r2.stdout.strip()
        except Exception:
            pass

    # Merge results
    if extra_out:
        if out:
            combined = out + "\n" + extra_out
            # Deduplicate lines
            seen = set()
            deduped = []
            for line in combined.splitlines():
                if line not in seen:
                    seen.add(line)
                    deduped.append(line)
            out = "\n".join(deduped)
        else:
            out = extra_out

    if out:
        if output_mode == "content" and len(out) > _GREP_BUDGET:
            return _build_grep_summary(out, pattern, path)
        return out
    return f"No matches found for pattern {pattern!r} in {path}"
