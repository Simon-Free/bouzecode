# [desc] Registers a project .bouzecode/ dir as extra source and returns a summary of its contents. [/desc]
"""LoadProjectConfig tool implementation."""
from __future__ import annotations

import json
from pathlib import Path

from ...core.paths import add_extra_dir


def _load_project_config(path: str) -> str:
    """Register a project's .bouzecode/ directory and return a summary of its contents."""
    project_root = Path(path).resolve()
    bouzecode_dir = project_root / ".bouzecode"

    if not bouzecode_dir.is_dir():
        return f"Error: No .bouzecode/ directory found at {project_root}"

    added = add_extra_dir(bouzecode_dir)

    # NOTE: plugin tool registration / MCP server connection were removed with the
    # plugin.loader and mcp modules; the summary below just lists what's on disk.
    sections = []

    # Skills
    skills_dir = bouzecode_dir / "skills"
    if skills_dir.is_dir():
        skill_files = sorted(skills_dir.glob("*.md"))
        if skill_files:
            lines = [f"Skills ({len(skill_files)}):"]
            for sf in skill_files:
                desc = _extract_skill_description(sf)
                lines.append(f"  - {sf.stem}" + (f" — {desc}" if desc else ""))
            sections.append("\n".join(lines))

    # MCP config
    mcp_file = bouzecode_dir / "mcp.json"
    if mcp_file.is_file():
        try:
            data = json.loads(mcp_file.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            lines = [f"MCP servers ({len(servers)}):"]
            for name in sorted(servers):
                lines.append(f"  - {name}")
            sections.append("\n".join(lines))
        except (json.JSONDecodeError, OSError):
            sections.append("MCP config: (parse error)")

    # Plugins
    plugins_dir = bouzecode_dir / "plugins"
    if plugins_dir.is_dir():
        plugin_dirs = [d for d in sorted(plugins_dir.iterdir()) if d.is_dir()]
        if plugin_dirs:
            lines = [f"Plugins ({len(plugin_dirs)}):"]
            for pd in plugin_dirs:
                lines.append(f"  - {pd.name}")
            sections.append("\n".join(lines))

    # Hooks
    hooks_dir = bouzecode_dir / "hooks"
    if hooks_dir.is_dir():
        hook_files = sorted(hooks_dir.glob("*.py"))
        if hook_files:
            lines = [f"Hooks ({len(hook_files)}):"]
            for hf in hook_files:
                lines.append(f"  - {hf.name}")
            sections.append("\n".join(lines))

    if not sections:
        summary = "(empty — no skills, MCP config, plugins, or hooks found)"
    else:
        summary = "\n\n".join(sections)

    status = "Registered" if added else "Already registered"
    return (
        f"{status}: {bouzecode_dir}\n\n"
        f"{summary}\n\n"
        "→ Skills and plugins from this project will be active starting next turn."
    )


def _extract_skill_description(path: Path) -> str:
    """Extract description from skill markdown frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return ""
        end = text.find("---", 3)
        if end == -1:
            return ""
        frontmatter = text[3:end]
        for line in frontmatter.splitlines():
            if line.strip().startswith("description:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""
