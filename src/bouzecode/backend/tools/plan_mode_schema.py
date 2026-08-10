# [desc] Hides the write tools from the tool schemas while plan mode is active, and puts them back on exit. [/desc]
"""Plan mode = the last place where a tool stayed IN the schema while being refused.

`get_tool_schemas()` already drops disabled tools, so the profile whitelist never
offers what it forbids. Plan mode did: Write/Edit/NotebookEdit kept their schema and
were rejected at permission time. Hiding them costs nothing and SHRINKS the cached
prompt prefix; the plan itself is written with `WritePlan`, which is framework
always-on and therefore never hidden.
"""
from __future__ import annotations

_HIDDEN_IN_PLAN_MODE = ("Write", "Edit", "NotebookEdit")
_CONFIG_KEY = "_plan_mode_hidden_tools"


def hide_write_tools(config: dict) -> None:
    """Drop the write tools from this agent's schema view for the plan-mode span."""
    from ..core.tool_registry import disable_tool, get_tool, is_enabled

    hidden = []
    for name in _HIDDEN_IN_PLAN_MODE:
        if get_tool(name) is not None and is_enabled(name):
            disable_tool(name)
            hidden.append(name)
    config[_CONFIG_KEY] = hidden


def restore_write_tools(config: dict) -> None:
    """Give back exactly the tools `hide_write_tools` took away (and nothing else)."""
    from ..core.tool_registry import enable_tool

    for name in config.pop(_CONFIG_KEY, []):
        enable_tool(name)
