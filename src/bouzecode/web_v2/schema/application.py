# [desc] Une application Flask qui n'enregistre QUE les routes de web_v2, pour dériver le schéma sans démarrer de serveur (ni migration, ni watchdog). [/desc]
from __future__ import annotations

from flask import Flask

from . import build_api_schema


def application_des_routes() -> Flask:
    from ..routes import register_routes
    app = Flask("bouzecode_web_v2_schema")
    register_routes(app)
    return app


def schema_des_routes() -> dict:
    return build_api_schema(application_des_routes())
