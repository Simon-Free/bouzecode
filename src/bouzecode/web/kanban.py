# [desc] Kanban board service — per-project task cards with JSON persistence and CRUD operations. [/desc]
"""Kanban board service for BouzéqUI — per-project task cards."""

import json
import uuid
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime, timezone
from pathlib import Path

from bouzecode.backend.commands.session import _safe_write_json, _rotate_backup

KANBAN_DIR = Path.home() / ".bouzecode" / "kanban"


@dataclass
class KanbanCard:
    id: str
    project: str
    title: str
    description: str
    status: str = "backlog"
    agent_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    archived: bool = False

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


def _project_file(project: str) -> Path:
    return KANBAN_DIR / f"{project}.json"


def _load(project: str) -> list[dict]:
    f = _project_file(project)
    if not f.exists():
        return _try_load_bak(project)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return _try_load_bak(project)
        return data
    except (json.JSONDecodeError, ValueError):
        return _try_load_bak(project)


def _try_load_bak(project: str) -> list[dict]:
    """Attempt recovery from .bak.json file (last known-good state, created by _rotate_backup)."""
    bak = _project_file(project).with_suffix(".bak.json")
    if not bak.exists():
        return []
    try:
        data = json.loads(bak.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _save(project: str, cards: list[dict]):
    KANBAN_DIR.mkdir(parents=True, exist_ok=True)
    target = _project_file(project)
    _rotate_backup(target)
    _safe_write_json(target, cards, indent=2)


def list_cards(project: str) -> list[KanbanCard]:
    return [KanbanCard(**c) for c in _load(project)]


def get_card(project: str, card_id: str) -> KanbanCard | None:
    for c in _load(project):
        if c["id"] == card_id:
            return KanbanCard(**c)
    return None


def create_card(project: str, title: str, description: str) -> KanbanCard:
    card = KanbanCard(
        id=uuid.uuid4().hex[:8],
        project=project,
        title=title,
        description=description,
    )
    cards = _load(project)
    cards.append(asdict(card))
    _save(project, cards)
    return card


def update_card(project: str, card_id: str, **kwargs) -> KanbanCard | None:
    cards = _load(project)
    for c in cards:
        if c["id"] == card_id:
            valid_fields = {f.name for f in fields(KanbanCard)} - {"id", "project", "created_at"}
            for k, v in kwargs.items():
                if k in valid_fields and v is not None:
                    c[k] = v
            c["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save(project, cards)
            return KanbanCard(**c)
    return None


def delete_card(project: str, card_id: str) -> bool:
    cards = _load(project)
    new = [c for c in cards if c["id"] != card_id]
    if len(new) == len(cards):
        return False
    _save(project, new)
    return True
