# [desc] API projets: ouvrir/lister/fermer, agents par projet, liste des modèles du registry. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .._body import json_body
from ....backend.agent.providers.registry import PROVIDERS
from ...services.work import projects

projects_bp = Blueprint("projects_api", __name__)


@projects_bp.get("/api/projects")
def api_projects_overview():
    return jsonify({"projects": projects.overview()})


@projects_bp.get("/api/projects/logical")
def api_projects_logical():
    """Projets regroupés par dépôt git (un projet logique = un dépôt, ses worktrees
    = ses branches). Dérivé, ne modifie pas projects.json."""
    return jsonify({"projects": projects.logical_overview()})


@projects_bp.post("/api/projects")
def api_projects_add():
    payload = json_body(request)
    name = (payload.get("name") or "").strip()
    path = (payload.get("path") or "").strip()
    description = (payload.get("description") or "").strip()
    if not name or not path:
        return jsonify({"error": "name et path requis"}), 400
    result = projects.add_project(name, path, description)
    if isinstance(result, str):
        return jsonify({"error": result}), 400
    return jsonify(result)


@projects_bp.patch("/api/projects/<slug>")
def api_projects_update(slug: str):
    payload = json_body(request)
    description = (payload.get("description") or "").strip()
    result = projects.update_project(slug, description)
    if result is None:
        return jsonify({"error": f"projet inconnu: {slug}"}), 404
    return jsonify(result)


@projects_bp.delete("/api/projects/<slug>")
def api_projects_remove(slug: str):
    if not projects.remove_project(slug):
        return jsonify({"error": f"projet inconnu: {slug}"}), 404
    return jsonify({"ok": True})


@projects_bp.get("/api/projects/<slug>/agents")
def api_project_agents(slug: str):
    project = projects.find(slug)
    if project is None:
        return jsonify({"error": f"projet inconnu: {slug}"}), 404
    return jsonify({"agents": projects.agents_of(project)})


@projects_bp.get("/api/models")
def api_models():
    models = [
        {"name": model, "provider": provider_name}
        for provider_name, provider in PROVIDERS.items()
        for model in provider["models"]
    ]
    return jsonify({"models": models, "default": ""})
