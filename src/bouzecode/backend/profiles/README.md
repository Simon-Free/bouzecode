# profiles/

## Purpose
Agent profiles: a YAML declaration of what an agent is made of (model, tools, skills, hooks, required plugins, extra prompt prose). This package defines the dataclass, loads profiles from an ordered set of directories, merges several into one, and can pull a shared catalog from a git repo. The `builtin/` directory holds the profiles shipped with the package as YAML only — no Python.

## Usage
- `models.py` — `AgentProfile` dataclass: `name`, `description`, `skills`, `tools`, `hooks`, `requires_plugins`, `model`, `system_prompt_extra`, `kind` (user / system / fragment / app), `plan_mode`, `require_recap`, `inherit_default`
- `loader.py` — `load_profile_from_path`, `load_profiles_from_dir` (YAML to `AgentProfile`)
- `discovery.py` — the ordered search path (builtin, then user-global, then project, then extra dirs): `builtin_dir`, `user_global_dir`, `profile_search_dirs`, `load_system_profiles`, `load_user_profiles`, `load_all_profiles`, `resolve_agent_profile`
- `composer.py` — `merge_profiles`: ordered union for list fields, last-wins for `model`
- `catalog.py` — the remote shared catalog: `refresh_catalog` (clone or fast-forward pull), `list_catalog_profiles`, `is_installed`, `installed_and_available`, `CATALOG_DIR`. The repo URL is never hardcoded; it comes from an environment variable or from the configured base URL plus a path
- `__init__.py` re-exports the public surface
