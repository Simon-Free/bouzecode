# [desc] Per-project TODO notepad persistence — load/save plain text notes to kanban directory [/desc]
"""TODO notepad service — per-project load/save from ~/.bouzecode/kanban/<project>/todo.md."""

from pathlib import Path

from ..web.kanban import KANBAN_DIR


def _todo_file(project: str) -> Path:
    return KANBAN_DIR / project / "todo.md"


def load(project: str) -> str:
    f = _todo_file(project)
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8")


def save(project: str, content: str) -> None:
    f = _todo_file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
