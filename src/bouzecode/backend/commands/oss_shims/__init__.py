"""OSS feature shims — thin wrappers that wire flat-package features into the new engine dispatcher."""
from __future__ import annotations

from .voice_cmd import cmd_voice
from .mcp_cmd import cmd_mcp
from .plugin_cmd import cmd_plugin
from .memory_cmd import cmd_memory
from .video_cmd import cmd_video

OSS_COMMANDS = {
    "voice": cmd_voice,
    "mcp": cmd_mcp,
    "plugin": cmd_plugin,
    "memory": cmd_memory,
    "video": cmd_video,
}

__all__ = ["OSS_COMMANDS", "cmd_voice", "cmd_mcp", "cmd_plugin", "cmd_memory", "cmd_video"]
