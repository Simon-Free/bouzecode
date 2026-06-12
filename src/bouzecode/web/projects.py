# [desc] Project registry for BouzéqUI — persists projects as JSON with add/remove/list operations. [/desc]
"""Project registry for BouzéqUI — persists projects as JSON."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

PROJECTS_FILE = Path.home() / ".bouzecode" / "projects.json"


@dataclass
class Project:
    name: str
    path: str


def _load() -> list[dict]:
    if not PROJECTS_FILE.exists():
        return []
    return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))


def _save(projects: list[dict]):
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")


def list_projects() -> list[Project]:
    return [Project(**p) for p in _load()]


def add_project(name: str, path: str) -> Project:
    projects = _load()
    for p in projects:
        if p["name"] == name:
            p["path"] = path
            _save(projects)
            return Project(name=name, path=path)
    proj = Project(name=name, path=path)
    projects.append(asdict(proj))
    _save(projects)
    return proj


def remove_project(name: str) -> bool:
    projects = _load()
    new = [p for p in projects if p["name"] != name]
    if len(new) == len(projects):
        return False
    _save(new)
    return True
