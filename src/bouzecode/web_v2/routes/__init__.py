# [desc] Enregistrement des blueprints API web_v2. [/desc]
from flask import Flask

from .sessions import sessions_bp
from .typologies import typologies_bp
from .env_sanity import env_sanity_bp
from .interrupted import interrupted_bp
from .search import search_bp
from .version import version_bp
from .work import builder_bp, fleet_bp, projects_bp, tickets_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(sessions_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(builder_bp)
    app.register_blueprint(typologies_bp)
    app.register_blueprint(version_bp)
    app.register_blueprint(env_sanity_bp)
    app.register_blueprint(interrupted_bp)
    app.register_blueprint(search_bp)
