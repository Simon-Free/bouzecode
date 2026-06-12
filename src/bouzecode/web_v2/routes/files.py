# [desc] API explorateur: arborescence/contenu multi-racines (projets), pygments, CSS de coloration. [/desc]
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from ..services import file_service

files_bp = Blueprint("files_api", __name__)


def _root_or_404():
    root = file_service.resolve_root(request.args.get("root") or None)
    if root is None:
        return None, (jsonify({"error": "projet inconnu"}), 404)
    return root, None


@files_bp.get("/api/files/tree")
def api_files_tree():
    root, error = _root_or_404()
    if error:
        return error
    relative = request.args.get("path", "")
    entries = file_service.list_dir(relative, root)
    if entries is None:
        return jsonify({"error": f"dossier introuvable: {relative}"}), 404
    return jsonify({"path": relative, "root": str(root), "entries": entries})


@files_bp.get("/api/files/content")
def api_files_content():
    root, error = _root_or_404()
    if error:
        return error
    relative = request.args.get("path", "")
    result = file_service.read_file(relative, root, want_highlight=bool(request.args.get("hl")))
    if result is None:
        return jsonify({"error": f"fichier introuvable: {relative}"}), 404
    return jsonify(result)


@files_bp.get("/api/files/pygments.css")
def api_pygments_css():
    return Response(file_service.pygments_css(), mimetype="text/css")
