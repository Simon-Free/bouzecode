# [desc] Plugin system types: manifest (tools/skills/deps), registry entry, and scope. [/desc]
"""Plugin system types: manifest, entry, scope.

A bouzecode plugin is a pip-installable package (published on PyPI or a private
package index) that
ships a ``plugin.json`` at its import root. The manifest lists the python modules
exporting ``TOOL_DEFS`` and/or skill ``.md`` files, plus the pip ``dependencies``
pulled in at install time so the plugin is self-contained.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PluginScope(str, Enum):
    USER    = "user"     # ~/.bouzecode/plugins.json
    PROJECT = "project"  # <cwd>/.bouzecode/plugins.json


@dataclass
class PluginManifest:
    """Parsed from a plugin package's ``plugin.json``."""
    name: str
    package: str = ""                                          # pip distribution name
    version: str = "0.1.0"
    description: str = ""
    tools: list[str] = field(default_factory=list)            # modules exporting TOOL_DEFS
    hooks: list[str] = field(default_factory=list)            # modules exporting HOOK_DEFS
    skills: list[str] = field(default_factory=list)           # skill .md files (relative)
    dependencies: list[str] = field(default_factory=list)     # pip packages

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        return cls(
            name=data.get("name", "unknown"),
            package=data.get("package", ""),
            version=str(data.get("version", "0.1.0")),
            description=data.get("description", ""),
            tools=list(data.get("tools", [])),
            hooks=list(data.get("hooks", [])),
            skills=list(data.get("skills", [])),
            dependencies=list(data.get("dependencies", [])),
        )

    @classmethod
    def from_import_root(cls, import_root: Path) -> "PluginManifest | None":
        """Load ``plugin.json`` shipped at a package's import root."""
        json_file = import_root / "plugin.json"
        if not json_file.exists():
            return None
        return cls.from_dict(json.loads(json_file.read_text(encoding="utf-8")))


@dataclass
class PluginEntry:
    """A plugin registered in plugins.json (one scope)."""
    name: str
    scope: PluginScope
    package: str             # pip distribution name (what was installed)
    import_root: Path        # directory holding plugin.json + tool modules
    enabled: bool = True
    manifest: PluginManifest | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope.value,
            "package": self.package,
            "import_root": str(self.import_root),
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginEntry":
        return cls(
            name=data["name"],
            scope=PluginScope(data.get("scope", "user")),
            package=data.get("package", ""),
            import_root=Path(data["import_root"]),
            enabled=data.get("enabled", True),
        )


def sanitize_plugin_name(name: str) -> str:
    """Make a plugin name safe as a dict key / directory name."""
    return re.sub(r"[^\w]", "_", name)
