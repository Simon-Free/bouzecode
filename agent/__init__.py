# [desc] Package entry point: re-exports core agent types, runner, DAG helpers, and registers built-in tools. [/desc]
from .state import AgentState, ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady
from .loop import run
from .dag import _build_alias_map, _build_dag_levels, _add_implicit_write_deps, _execute_level
from .permissions import _check_permission, _permission_desc, _propagate_denials
from providers import TextChunk, ThinkingChunk

import tools as _tools_init  # noqa: F401 — ensure built-in tools are registered

__all__ = [
    "AgentState", "run",
    "TextChunk", "ThinkingChunk",
    "ToolStart", "ToolEnd", "TurnDone", "PermissionRequest", "CheckpointReady",
]
