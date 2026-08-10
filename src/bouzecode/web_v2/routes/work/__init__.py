# [desc] Blueprints work: projets, tickets, manager (dispatch + arbre), agent-builder. [/desc]
from .builder import builder_bp
from .fleet import fleet_bp
from .projects import projects_bp
from .tickets import tickets_bp

__all__ = ["projects_bp", "tickets_bp", "fleet_bp", "builder_bp"]
