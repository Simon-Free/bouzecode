# [desc] Flask blueprint exposing GET /api/version returning boot vs current SHA drift state. [/desc]
from flask import Blueprint, jsonify

from .. import version as _version

version_bp = Blueprint("version", __name__)


@version_bp.get("/api/version")
def api_version():
    """dérive de version → {boot_sha, boot_version, current_head_sha, sha_drift, source_drift,
    drift} : état figé au boot (SHA + empreinte du source) vs HEAD et fichiers du disque relus
    toutes les 10 s max (le bandeau UI alerte quand le serveur tourne du code périmé)"""
    state = _version.cached_version_state(
        _version.BOOT_SHA,
        _version.BOOT_VERSION,
        _version.REPO_ROOT,
        _version.BOOT_SOURCE_FINGERPRINT,
        _version.SOURCE_ROOT,
    )
    # Le code que « Redémarrer » rechargera : celui du répertoire d'où ce process importe.
    return jsonify({**state, "code_root": _version.SOURCE_ROOT})
