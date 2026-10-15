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


def _dismiss_project(params: dict, config: dict) -> str:
    """Enregistre « ce dossier n'est PAS un projet », pour ne plus jamais le demander."""
    from ....web_v2.services.work.dismissed_paths import dismiss

    path = (params.get("path") or "").strip()
    if not path:
        return "Error: 'path' is required."
    entry = dismiss(path, reason=(params.get("reason") or "").strip())
    return (
        f"Noté : {entry['path']} n'est pas un projet"
        + (f" ({entry['reason']})" if entry["reason"] else "")
        + ". La question ne sera plus posée pour ce dossier."
    )


register_tool(ToolDef(
    name="DismissProject",
    schema={
        "name": "DismissProject",
        "description": (
            "Record that a directory is NOT a project, so the question is never asked "
            "again for it. Call this ONLY to transcribe an explicit user answer — never "
            "on your own initiative. The counterpart of AddProject."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path the user just said is not a project.",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional short reason, as given by the user (<=200 chars).",
                },
            },
            "required": ["path"],
        },
    },
    func=_dismiss_project,
    read_only=False,
    concurrent_safe=False,
))


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
