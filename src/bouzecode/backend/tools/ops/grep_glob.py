# [desc] Glob and grep search operations (ripgrep when available), with a compact summary when the output overflows. [/desc]
"""File search: `_glob` and `_grep`, plus the overflow summary they fall back to.

Split out of shell_search.py, which now keeps only shell EXECUTION. Both names
stay importable from shell_search for backwards compatibility."""
import functools
import os
import re
import subprocess
from pathlib import Path

from .glob_cap import cap_glob_matches

_GREP_BUDGET = 1000  # max chars before switching to summary mode

# Perf guards for ripgrep, applied on EVERY rg invocation regardless of git.
# rg respects .gitignore only inside a git repo; in a plain directory (no
# .gitignore) it would otherwise open every file, including multi-hundred-MB
# JSON/CSV dumps. These guards keep searches fast everywhere.
_MAX_FILESIZE = "5M"  # skip files larger than this (dumps/fixtures never code)
_DEFAULT_EXCLUDE_DIRS = [
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
]


def _rg_guards(with_max_size: bool = True) -> list:
    """Return default ripgrep guard flags (dir excludes + optional size cap).

    with_max_size=False for the include_patterns second pass, where the user
    explicitly re-includes files that may legitimately exceed the size cap.
    """
    flags = []
    if with_max_size:
        flags += ["--max-filesize", _MAX_FILESIZE]
    for d in _DEFAULT_EXCLUDE_DIRS:
        flags += ["-g", f"!{d}"]
    return flags


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
        cmd = ["rg", "--files", "--no-require-git"] + _rg_guards(True) + ["-g", pattern, str(base)]
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
                cmd2 = (["rg", "--files", "--no-require-git", "--no-ignore"]
                        + _rg_guards(False) + ["-g", ip, str(base)])
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
    # Also match temp (scratch) files: they live outside the worktree so rg/glob
    # never sees them, but the agent addresses them by logical paths that should
    # still resolve here. Report the REAL path with a [scratch] marker.
    scratch_hits = []
    try:
        from fnmatch import fnmatch
        from .scratch import all_temp_paths
        patt_base = pattern.lstrip("**/").lstrip("/")
        for logical, real in all_temp_paths():
            if fnmatch(Path(logical).name, patt_base) or fnmatch(logical, pattern):
                scratch_hits.append(f"[scratch] {real}")
    except Exception:
        scratch_hits = []
    if scratch_hits:
        matches = matches + sorted(set(scratch_hits))
    if not matches:
        return "No files matched"
    return cap_glob_matches(matches, pattern)


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
    if use_rg:
        cmd += _rg_guards(True)
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
        cmd2 = ["rg", "--no-heading", "--no-require-git", "--no-ignore"] + _rg_guards(False)
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

    # Also grep inside temp (scratch) files addressed by logical paths: they live
    # outside the worktree so rg never sees them. We scan each registered temp
    # file's real content for the pattern and prefix hits with [scratch].
    scratch_out = ""
    try:
        import re as _re
        from .scratch import all_temp_paths
        from .file_ops import read_text_raw
        flags = _re.IGNORECASE if case_insensitive else 0
        rx = _re.compile(pattern, flags)
        scratch_lines = []
        for logical, real in all_temp_paths():
            if glob and not __import__("fnmatch").fnmatch(Path(logical).name, glob):
                continue
            try:
                text = read_text_raw(Path(real))
            except Exception:
                continue
            if output_mode == "files_with_matches":
                if rx.search(text):
                    scratch_lines.append(f"[scratch] {real}")
            elif output_mode == "count":
                n = len(rx.findall(text))
                if n:
                    scratch_lines.append(f"[scratch] {real}:{n}")
            else:
                for i, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        scratch_lines.append(f"[scratch] {real}:{i}:{line}")
        scratch_out = "\n".join(scratch_lines)
    except Exception:
        scratch_out = ""

    if scratch_out:
        out = (out + "\n" + scratch_out) if out else scratch_out

    if out:
        if output_mode == "content" and len(out) > _GREP_BUDGET:
            return _build_grep_summary(out, pattern, path)
        return out
    return f"No matches found for pattern {pattern!r} in {path}"
