# [desc] Diffs HTML des file_snapshots d'une session (onglet « fichiers modifiés »). [/desc]
"""L'explorateur de fichiers (page /files et routes /api/files/*) a été retiré ; il ne
reste que le rendu des diffs de session, seul consommateur de ce module."""
from __future__ import annotations

import difflib
import html
import os
from pathlib import Path

ROOT = Path(os.environ.get("BOUZEUI2_ROOT", os.getcwd())).resolve()


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
