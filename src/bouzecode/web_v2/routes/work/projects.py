# [desc] API projets: ouvrir/lister/fermer, agents par projet, liste des modèles du registry. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ....backend.agent.providers.registry import PROVIDERS
from ...services.work import projects

projects_bp = Blueprint("projects_api", __name__)


@projects_bp.get("/api/projects")
def api_projects_overview():
    return jsonify({"projects": projects.overview()})


@projects_bp.post("/api/projects")
def api_projects_add():
    payload = request.get_json(force=True) or {}
    name = (payload.get("name") or "").strip()
    path = (payload.get("path") or "").strip()
    if not name or not path:
        return jsonify({"error": "name et path requis"}), 400
    result = projects.add_project(name, path)
    if isinstance(result, str):
        return jsonify({"error": result}), 400
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
