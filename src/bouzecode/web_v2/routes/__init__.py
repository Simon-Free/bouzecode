# [desc] Enregistrement des blueprints API web_v2. [/desc]
from flask import Flask

from .classify import classify_bp
from .files import files_bp
from .sessions import sessions_bp
from .typologies import typologies_bp
from .work import projects_bp, tickets_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(sessions_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(typologies_bp)
    app.register_blueprint(classify_bp)
