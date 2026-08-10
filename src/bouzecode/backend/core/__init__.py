# [desc] Package init re-exporting config, tool registry, and path utilities from the core subpackage. [/desc]
"""Core package — configuration, system prompt, paths, and tool registry."""
from .config import load_config, save_config  # noqa: F401
from .tool_registry import register_tool, get_all_tools, get_tool, ToolDef  # noqa: F401
from .paths import register_extra_dirs, get_extra_dirs  # noqa: F401
