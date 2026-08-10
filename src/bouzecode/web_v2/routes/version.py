# [desc] Flask blueprint exposing GET /api/version returning boot vs current SHA drift state. [/desc]
from flask import Blueprint, jsonify

from .. import version as _version

version_bp = Blueprint("version", __name__)


@version_bp.get("/api/version")
def api_version():
    state = _version.cached_version_state(
        _version.BOOT_SHA,
        _version.BOOT_VERSION,
        _version.REPO_ROOT,
        _version.BOOT_SOURCE_FINGERPRINT,
        _version.SOURCE_ROOT,
    )
    return jsonify(state)
