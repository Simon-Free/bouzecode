# tools/projects_tool/

## Purpose
The `AddProject` tool: lets the model register a project directory into the shared web
project list so it becomes selectable when launching agents.

## Usage
- `tools.py` — `_add_project`, registered as `AddProject` (not read-only, not concurrent-safe). Requires `name` and `path`, takes an optional `description`, and returns the resulting slug. The web service is imported lazily inside the handler so tool boot never pulls Flask in
