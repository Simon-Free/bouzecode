# [desc] Blueprints work: projets, flotte (arbre, activité), agent-builder, Bureau. Les tickets vivent dans `routes/tickets_api`. [/desc]
from .builder import builder_bp
from .builder_plugins import builder_plugins_bp
from .assistant import assistant_bp
from .decisions import decisions_bp
from .fleet import fleet_bp
from .projects import projects_bp
from .tasks import tasks_bp

__all__ = ["projects_bp", "fleet_bp", "builder_bp", "builder_plugins_bp", "tasks_bp",
           "assistant_bp", "decisions_bp"]
