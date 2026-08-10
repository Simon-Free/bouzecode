"""Routes du rapport des agents interrompus par le dernier arrêt serveur.

GET  /api/interrupted          → snapshot figé au boot {boot_at, items[], dismissed}
POST /api/interrupted/dismiss  → masque le bandeau (persisté ; ne réapparaît pas seul)
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from bouzecode.web_v2.services.work import interrupted_report

interrupted_bp = Blueprint("interrupted_api", __name__)


@interrupted_bp.get("/api/interrupted")
def api_interrupted():
    return jsonify(interrupted_report.read_report())


@interrupted_bp.post("/api/interrupted/dismiss")
def api_interrupted_dismiss():
    interrupted_report.dismiss()
    return jsonify({"ok": True})
