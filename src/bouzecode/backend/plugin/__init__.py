# [desc] Plugin system package: types, store ops, and loader for pip-installed bouzecode plugins. [/desc]
"""Plugin system for bouzecode (pip packages from a package index)."""
from .types import PluginEntry, PluginManifest, PluginScope
from .store import (
    install_plugin, list_plugins, get_plugin,
    enable_plugin, disable_plugin,
)
from .loader import register_plugin_tools, register_plugin_hooks, load_plugin_skills

__all__ = [
    "PluginEntry", "PluginManifest", "PluginScope",
    "install_plugin", "list_plugins", "get_plugin",
    "enable_plugin", "disable_plugin",
    "register_plugin_tools", "register_plugin_hooks", "load_plugin_skills",
]
