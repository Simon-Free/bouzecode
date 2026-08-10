# [desc] Flask blueprint exposing GET /api/search to search agent conversations by keyword (AND match, scope open/all). [/desc]
"""Blueprint for keyword search across agent conversations."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services.search import search_agents

search_bp = Blueprint("search", __name__)


@search_bp.get("/api/search")
def api_search():
    """Search agent conversations by keyword.

    Query params: q (space-separated words, AND match), scope (open|all, default open).
    """
    query = request.args.get("q", "")
    scope = request.args.get("scope", "open")
    if scope not in ("open", "all"):
        scope = "open"
    return jsonify({"results": search_agents(query, scope)})
