# [desc] Registers the AddProject tool letting the model add projects to the web_v2 registry (lazy web_v2 import). [/desc]
"""AddProject — lets the model register a project into the web_v2 project list.

Writes to the SHARED global state ~/.bouzecode/web_v2/projects.json via the web_v2
service. Import of web_v2 is done lazily inside the handler so importing this module
at agent boot never pulls the Flask app in.
"""
from __future__ import annotations

from ...core.tool_registry import ToolDef, register_tool


def _add_project(params: dict, config: dict) -> str:
    # Lazy import: keep web_v2 (Flask) out of the tools boot import graph.
    from ....web_v2.services.work.projects import add_project

    name = (params.get("name") or "").strip()
    path = (params.get("path") or "").strip()
    description = (params.get("description") or "").strip()
    if not name or not path:
        return "Error: 'name' and 'path' are both required."
    result = add_project(name, path, description)
    if isinstance(result, str):
        return f"Error: {result}"
    return (
        f"Project added: {result['name']} (slug={result['slug']}) at {result['path']}"
        + (f" — {result['description']}" if result.get("description") else "")
    )


register_tool(ToolDef(
    name="AddProject",
    schema={
        "name": "AddProject",
        "description": (
            "Register a new project into the bouzecode web_v2 project list so it becomes "
            "selectable when launching agents. Persists to the shared global project registry. "
            "Provide an absolute path to an existing directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable project name (used to derive the slug).",
                },
                "path": {
                    "type": "string",
                    "description": "Absolute path to the existing project directory.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional short description of the project (<=200 chars).",
                },
            },
            "required": ["name", "path"],
        },
    },
    func=_add_project,
    read_only=False,
    concurrent_safe=False,
))
