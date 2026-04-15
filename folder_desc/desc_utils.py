# [desc] Utilities for wrapping, extracting, and managing `[desc]` tags as comments across multiple languages. [/desc]
from __future__ import annotations

import re
import subprocess
from pathlib import Path

COMMENT_STYLES = {
    "line_hash":  ("#",  None,   None),
    "line_slash": ("//", None,   None),
    "block_c":    (None, "/*",   "*/"),
    "block_html": (None, "<!--", "-->"),
    "line_dash":  ("--", None,   None),
}

EXT_TO_STYLE = {
    ".py": "line_hash", ".sh": "line_hash", ".bash": "line_hash",
    ".rb": "line_hash", ".yml": "line_hash", ".yaml": "line_hash",
    ".js": "line_slash", ".ts": "line_slash", ".jsx": "line_slash",
    ".tsx": "line_slash", ".java": "line_slash", ".go": "line_slash",
    ".rs": "line_slash", ".c": "line_slash", ".cpp": "line_slash",
    ".h": "line_slash", ".hpp": "line_slash", ".swift": "line_slash",
    ".css": "block_c", ".scss": "block_c", ".less": "block_c",
    ".html": "block_html", ".htm": "block_html", ".svg": "block_html",
    ".vue": "block_html", ".svelte": "block_html",
    ".lua": "line_dash", ".sql": "line_dash",
}

_DESC_RE = re.compile(r'\[desc\]\s*(.*?)\s*\[/desc\]', re.DOTALL)


def _style_for(ext: str) -> tuple[str | None, str | None, str | None] | None:
    key = EXT_TO_STYLE.get(ext.lower())
    return COMMENT_STYLES.get(key) if key else None


def wrap_description(text: str, ext: str) -> str:
    style = _style_for(ext)
    if style is None:
        return ""
    line_pfx, block_start, block_end = style

    if line_pfx:
        lines = text.strip().splitlines()
        if len(lines) == 1:
            return f"{line_pfx} [desc] {lines[0]} [/desc]"
        parts = [f"{line_pfx} [desc] {lines[0]}"]
        for l in lines[1:-1]:
            parts.append(f"{line_pfx} {l}")
        parts.append(f"{line_pfx} {lines[-1]} [/desc]")
        return "\n".join(parts)

    lines = text.strip().splitlines()
    if len(lines) == 1:
        return f"{block_start} [desc] {lines[0]} [/desc] {block_end}"
    inner = "\n     ".join(lines)
    return f"{block_start} [desc] {inner} [/desc] {block_end}"


def extract_description(content: str) -> tuple[str | None, int, int]:
    head = "\n".join(content.splitlines()[:10])
    m = _DESC_RE.search(head)
    if not m:
        return None, 0, 0
    raw = m.group(1)
    raw = re.sub(r'\n\s*(?:#|//|--|[*])\s*', ' ', raw)
    return raw.strip(), m.start(), m.end()


def _find_desc_line_range(content: str) -> tuple[int, int] | None:
    lines = content.splitlines(keepends=True)
    start = end = None
    for i, line in enumerate(lines[:10]):
        if '[desc]' in line and start is None:
            start = i
        if '[/desc]' in line:
            end = i + 1
            break
    if start is not None and end is not None:
        return start, end
    return None


_ALWAYS_SKIP = {'.venv', 'node_modules', '__pycache__', 'build', 'dist', '.git',
                '.egg-info', '.tox', '.mypy_cache', '.pytest_cache'}


def _is_ignored(path: Path, root: Path) -> bool:
    rel = str(path.relative_to(root))
    if any(part in _ALWAYS_SKIP or part.endswith('.egg-info') for part in path.parts):
        return True
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=str(root), capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False
