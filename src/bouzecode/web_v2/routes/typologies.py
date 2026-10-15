# [desc] Blueprint exposing GET /api/typologies endpoint to list agent typologies scoped by project. [/desc]
"""Blueprint for typology listing."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services.typologies import list_typologies
from ..services.work import projects

typologies_bp = Blueprint("typologies", __name__)


@typologies_bp.get("/api/typologies")
def api_typologies():
    """?project=<slug> — typologies d'agents déclarées (projet + global)"""
    slug = request.args.get("project", "")
    project_path: str | None = None
    if slug:
        project = projects.find(slug)
        if project:
            project_path = project["path"]
    return jsonify({"typologies": list_typologies(project_path)})
