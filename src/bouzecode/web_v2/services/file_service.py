# [desc] Explorateur lecture seule multi-racines (projets), coloration pygments, diffs des snapshots. [/desc]
"""Chemins strictement bornés à une racine autorisée : la racine serveur ou un projet ouvert."""
from __future__ import annotations

import difflib
import html
import os
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

ROOT = Path(os.environ.get("BOUZEUI2_ROOT", os.getcwd())).resolve()
IGNORED_DIRS = {
    ".git", ".venv", ".venv-ui", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".ruff_cache", ".idea", ".rope_project",
}
MAX_FILE_CHARS = 400_000
MAX_HIGHLIGHT_CHARS = 200_000
_FORMATTER = HtmlFormatter(style="native", cssclass="hl", linenos="table")


def pygments_css() -> str:
    return _FORMATTER.get_style_defs(".hl")


def resolve_root(project_slug: str | None) -> Path | None:
    """Racine autorisée: défaut serveur, ou le path d'un projet ouvert."""
    if not project_slug:
        return ROOT
    from .work import projects
    project = projects.find(project_slug)
    return Path(project["path"]) if project else None


def _is_secret(name: str) -> bool:
    return name.startswith(".env") or name.endswith((".pem", ".key"))


def safe_resolve(relative: str, root: Path) -> Path | None:
    path = (root / relative).resolve()
    return path if path == root or path.is_relative_to(root) else None


def list_dir(relative: str, root: Path) -> list[dict] | None:
    directory = safe_resolve(relative, root)
    if directory is None or not directory.is_dir():
        return None
    entries = []
    for child in directory.iterdir():
        if child.name in IGNORED_DIRS or _is_secret(child.name):
            continue
        entries.append({
            "name": child.name,
            "path": child.relative_to(root).as_posix(),
            "dir": child.is_dir(),
            "size": child.stat().st_size if child.is_file() else 0,
        })
    entries.sort(key=lambda entry: (not entry["dir"], entry["name"].lower()))
    return entries


def _highlight(text: str, filename: str) -> str:
    try:
        lexer = get_lexer_for_filename(filename)
    except ClassNotFound:
        lexer = TextLexer()
    return highlight(text, lexer, _FORMATTER)


def read_file(relative: str, root: Path, want_highlight: bool = False) -> dict | None:
    path = safe_resolve(relative, root)
    if path is None or not path.is_file() or _is_secret(path.name):
        return None
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        return {"path": relative, "binary": True, "size": len(raw), "content": "", "truncated": False}
    text = raw.decode("utf-8", errors="replace")
    truncated = len(text) > MAX_FILE_CHARS
    result = {
        "path": relative, "binary": False, "size": len(raw),
        "content": text[:MAX_FILE_CHARS], "truncated": truncated,
    }
    if want_highlight and len(text) <= MAX_HIGHLIGHT_CHARS:
        result["html"] = _highlight(text, path.name)
    return result


def _diff_html(before: str, after: str) -> str:
    diff_lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), "avant", "après", lineterm="", n=3
    )
    rendered = []
    for line in diff_lines:
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            css = "hunk"
        elif line.startswith("+"):
            css = "add"
        elif line.startswith("-"):
            css = "del"
        else:
            css = "ctx"
        rendered.append(f'<div class="dl {css}">{html.escape(line)}</div>')
    return "".join(rendered) or '<div class="dl ctx">(aucune différence textuelle)</div>'


def render_snapshot_diffs(snapshots: dict) -> list[dict]:
    """file_snapshots de session JSON → diffs HTML prêts à afficher."""
    diffs = []
    for path, snapshot in sorted(snapshots.items()):
        before = snapshot.get("before") or ""
        after = snapshot.get("after") or ""
        diffs.append({
            "path": path,
            "is_new": bool(snapshot.get("is_new")),
            "added": sum(1 for l in difflib.ndiff(before.splitlines(), after.splitlines()) if l.startswith("+ ")),
            "html": _diff_html(before, after),
        })
    return diffs
