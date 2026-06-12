# [desc] Registre des projets ouverts + agents par projet + compteurs d'actions requises. [/desc]
from __future__ import annotations

import json
import re
from pathlib import Path

from ....web import runner
from ..sessions import store

PROJECTS_PATH = Path.home() / ".bouzecode" / "web_v2" / "projects.json"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "projet"


def list_projects() -> list[dict]:
    if not PROJECTS_PATH.is_file():
        return []
    projects = json.loads(PROJECTS_PATH.read_text(encoding="utf-8"))
    return projects if isinstance(projects, list) else []


def _save(projects: list[dict]) -> None:
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROJECTS_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(PROJECTS_PATH)


def add_project(name: str, path: str) -> dict | str:
    """Retourne le projet créé, ou un message d'erreur."""
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        return f"dossier introuvable: {path}"
    slug = slugify(name)
    projects = list_projects()
    if any(p["slug"] == slug for p in projects):
        return f"projet déjà ouvert: {slug}"
    project = {"name": name.strip(), "slug": slug, "path": str(resolved.resolve())}
    projects.append(project)
    _save(projects)
    return project


def remove_project(slug: str) -> bool:
    projects = list_projects()
    remaining = [p for p in projects if p["slug"] != slug]
    if len(remaining) == len(projects):
        return False
    _save(remaining)
    return True


def find(slug: str) -> dict | None:
    return next((p for p in list_projects() if p["slug"] == slug), None)


def _belongs_to(agent_cwd: str, project_path: str) -> bool:
    if not agent_cwd:
        return False
    cwd = Path(agent_cwd)
    target = Path(project_path)
    return cwd == target or target in cwd.parents


def agents_of(project: dict, agents: list | None = None) -> list[dict]:
    """Agents web dont le cwd est dans le projet, avec statut live (du plus récent au plus ancien).

    If *agents* is provided (list of Agent objects), uses that instead of calling list_agents().
    This avoids redundant disk reads when the caller already has the full list.
    """
    all_agents = agents if agents is not None else runner.list_agents()
    rows = []
    for agent in all_agents:
        if not _belongs_to(agent.cwd, project["path"]):
            continue
        rows.append({
            "key": f"agent/{agent.agent_id}",
            "agent_id": agent.agent_id,
            "title": (agent.prompt or "").strip().split("\n")[0][:90],
            "model": agent.model,
            "started_at": agent.started_at,
            "status": store.agent_status(agent),
        })
    rows.sort(key=lambda row: row["started_at"], reverse=True)
    return rows


def overview() -> list[dict]:
    """Projets + compteurs pour la home: où dois-je agir ?"""
    from . import tickets as tickets_service
    all_agents = runner.list_agents()  # single call for all projects
    result = []
    for project in list_projects():
        agents = agents_of(project, agents=all_agents)
        project_tickets = tickets_service.list_tickets(project["slug"], refresh=True)
        statuses = [tickets_service.derive_status(t) for t in project_tickets]
        result.append({
            **project,
            "agents_running": sum(1 for a in agents if a["status"]["state"] == "running"),
            "agents_awaiting": sum(1 for a in agents if a["status"]["state"] == "awaiting_input"),
            "tickets_to_review": statuses.count("à relire"),
            "validations_ko": sum(
                1 for t in project_tickets for r in t["runs"]
                if r["kind"].startswith("validate") and r.get("verdict") == "KO"
            ),
            "tickets_total": len(project_tickets),
        })
    return result
