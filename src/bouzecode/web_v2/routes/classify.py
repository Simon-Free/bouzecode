# [desc] Blueprint exposing POST /api/classify endpoint that infers title, project, and typology from a prompt. [/desc]
"""Blueprint for prompt classification."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services.classify import classify_prompt
from ..services.typologies import list_typologies
from ..services.work import projects

classify_bp = Blueprint("classify", __name__)


@classify_bp.post("/api/classify")
def api_classify():
    """Classify a prompt: infer title, project, and typology."""
    payload = request.get_json(force=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt requis"}), 400

    # Gather context for the classifier
    project_list = projects.list_projects()
    # Determine project path for typologies (use hint if provided)
    hint_slug = payload.get("project_slug") or ""
    project_path: str | None = None
    if hint_slug:
        p = projects.find(hint_slug)
        if p:
            project_path = p["path"]
    typology_list = list_typologies(project_path)

    result = classify_prompt(prompt, project_list, typology_list)
    return jsonify(result)
