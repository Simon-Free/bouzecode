# [desc] Enregistrement des blueprints API web_v2. [/desc]
from flask import Flask

from .sessions import sessions_bp
from .enquete import enquete_bp
from .server import server_bp
from .typologies import typologies_bp
from .env_sanity import env_sanity_bp
from .schema import schema_bp
from .search import search_bp
from .version import version_bp
from .tickets_api import BLUEPRINTS as TICKETS_API
from .work import (assistant_bp, builder_bp, builder_plugins_bp, decisions_bp, fleet_bp,
                   projects_bp, tasks_bp)
from .work.inbox import inbox_bp
from .work.micros import micros_bp
from .work.signalements import signalements_bp


def register_routes(app: Flask) -> None:
    from ._errors import installer as installer_les_refus
    installer_les_refus(app)  # Refus de l'API tickets, 409 transition_refusee / deja_actif…
    app.register_blueprint(sessions_bp)
    app.register_blueprint(server_bp)
    app.register_blueprint(projects_bp)
    for blueprint in TICKETS_API:
        app.register_blueprint(blueprint)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(builder_bp)
    app.register_blueprint(builder_plugins_bp)
    app.register_blueprint(typologies_bp)
    app.register_blueprint(version_bp)
    app.register_blueprint(env_sanity_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(assistant_bp)
    app.register_blueprint(decisions_bp)
    app.register_blueprint(micros_bp)
    app.register_blueprint(inbox_bp)
    app.register_blueprint(signalements_bp)
    app.register_blueprint(enquete_bp)
    app.register_blueprint(schema_bp)
