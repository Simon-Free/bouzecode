# plugin/

## Purpose
Third-party extension packages that contribute tools, skills and MCP server configs. Plugins install into a user-level or project-level directory, are enabled per scope in a JSON config, and can also be discovered from directories listed in an environment variable.

## Usage
- `types.py` — `PluginScope`, `PluginManifest`, `PluginEntry`, `parse_plugin_identifier()`, `sanitize_plugin_name()` — manifest read from a plugin directory or from a markdown file, entries serialize to/from the config
- `store.py` — `install_plugin()`, `uninstall_plugin()`, `enable_plugin()`, `disable_plugin()`, `disable_all_plugins()`, `update_plugin()`, `list_plugins()`, `get_plugin()`, `install_dependencies()` — install from a local path or a git URL, persist entries, resolve the package manager
- `loader.py` — `load_all_plugins()`, `load_plugin_tools()`, `register_plugin_tools()`, `load_plugin_skills()`, `load_plugin_mcp_configs()`, `check_missing_deps()`, `ensure_plugin_dependencies()` — imports each plugin module under a unique name and retries once after installing missing dependencies
- `recommend.py` — `recommend_plugins()`, `recommend_from_files()`, `format_recommendations()`, `PluginRecommendation`, `BUILTIN_MARKETPLACE` — token-overlap scoring of installed and catalog plugins against the current context
- `__init__.py` re-exports the public surface
