# [desc] Service layer for listing, reading, and editing skill definitions across sources. [/desc]
# [desc] Service layer for listing, reading, and editing skill definitions across sources. [/desc]
"""List and edit skills from all skill paths (bouzecode + claude)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bouzecode.backend.tools.skill.loader import load_skills


@dataclass
class SkillView:
    name: str
    description: str
    source: str
    file_path: str
    is_builtin: bool

    @property
    def editable(self) -> bool:
        return not self.is_builtin and Path(self.file_path).exists()


def list_skill_views() -> list[SkillView]:
    views: list[SkillView] = []
    for skill in load_skills(include_builtins=True):
        views.append(
            SkillView(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                file_path=skill.file_path or "",
                is_builtin=(skill.source == "builtin"),
            )
        )
    views.sort(key=lambda view: (view.source, view.name))
    return views


def find_skill_view(name: str) -> SkillView | None:
    for view in list_skill_views():
        if view.name == name:
            return view
    return None


def read_skill_file(name: str) -> str:
    view = find_skill_view(name)
    if view is None or not view.editable:
        return ""
    return Path(view.file_path).read_text(encoding="utf-8")


def write_skill_file(name: str, content: str) -> bool:
    view = find_skill_view(name)
    if view is None or not view.editable:
        return False
    Path(view.file_path).write_text(content, encoding="utf-8")
    return True
