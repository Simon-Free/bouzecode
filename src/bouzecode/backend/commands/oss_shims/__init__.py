# [desc] Câblage des fonctionnalités OSS (paquets à plat) sur le dispatcher de commandes. [/desc]
"""OSS feature shims — thin wrappers that wire flat-package features into the new engine dispatcher.

Two conventions have to be met to be dispatchable, and both were missed:

* `dispatcher.handle_slash` appelle TOUJOURS `handler(args, state, config)`.
  `cmd_memory`, `cmd_mcp` et `cmd_plugin` étaient écrits `(args, config)` :
  `/memory`, `/mcp` et `/plugin` levaient un `TypeError` dès le premier usage.
* La valeur de retour est JETÉE par le dispatcher (seul un tuple sentinelle
  `__voice__`/… est relayé au REPL). Les shims qui construisent leur sortie sous
  forme de chaîne (`/mcp list`, `/memory list`, `/plugin list`) n'affichaient donc
  rien du tout. `_echoing` l'imprime.
"""
from __future__ import annotations

import functools

from .voice_cmd import cmd_voice
from .mcp_cmd import cmd_mcp
from .plugin_cmd import cmd_plugin
from .memory_cmd import cmd_memory
from .video_cmd import cmd_video
from .video_wizard_cmd import cmd_video_wizard


def _echoing(handler):
    """Print a shim's text result; pass any sentinel tuple through untouched."""
    @functools.wraps(handler)
    def _dispatch(args, state, config):
        result = handler(args, state, config)
        if isinstance(result, str):
            print(result)
            return None
        return result
    return _dispatch


OSS_COMMANDS = {
    "voice": _echoing(cmd_voice),
    "mcp": _echoing(cmd_mcp),
    "plugin": _echoing(cmd_plugin),
    "memory": _echoing(cmd_memory),
    "video": _echoing(cmd_video),
    "video-wizard": _echoing(cmd_video_wizard),
}

# Short help lines for `/help`, consumed by dispatcher._CMD_META.
OSS_COMMAND_META: dict[str, tuple[str, list[str]]] = {
    "voice":        ("Record a voice message and send it as a prompt", ["status"]),
    "mcp":          ("Manage MCP servers",  ["list", "reload", "add", "remove"]),
    "plugin":       ("Manage plugins",      ["list", "install", "uninstall",
                                             "enable", "disable", "load"]),
    "memory":       ("List / search stored memories", ["list", "search", "consolidate"]),
    "video":        ("Run the video pipeline for a topic", ["status"]),
    "video-wizard": ("Configure a video step by step, then run the pipeline", []),
}

__all__ = [
    "OSS_COMMANDS",
    "OSS_COMMAND_META",
    "cmd_voice", "cmd_mcp", "cmd_plugin", "cmd_memory",
    "cmd_video", "cmd_video_wizard",
]
