# [desc] Compatibility shim re-exporting backend tool registry so flat packages register into the engine. [/desc]
"""Tool registry compatibility shim.

Flat packages (memory/, plugin/) import from this module.
All calls are delegated to the canonical backend registry so that tools
registered here are visible to the engine.
"""
from bouzecode.backend.core.tool_registry import (  # noqa: F401
    ToolDef,
    register_tool,
    get_tool,
    get_all_tools,
    get_tool_schemas,
    execute_tool,
    clear_registry,
    unregister_tool,
    disable_tool,
    enable_tool,
    is_enabled,
    list_disabled,
    reset_disabled,
    ends_turn,
    is_concurrent_safe,
    push_local_overlay,
    pop_local_overlay,
)
