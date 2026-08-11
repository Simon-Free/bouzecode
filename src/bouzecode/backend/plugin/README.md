# plugin/

## Purpose
Third-party extension packages. A plugin is a pip-installable package declaring tools, hooks and skills; this package installs it, records it in a per-scope `plugins.json`, and imports its modules to register what it contributes.

## Usage
- `types.py` — `PluginScope` (where the registry file lives), `PluginManifest` (tools / skills / deps), `PluginEntry` (a registry row: name, package, modules, enabled flag), `sanitize_plugin_name`
- `store.py` — `install_plugin` (from a package index, a git source, or a local path), `list_plugins`, `get_plugin`, `enable_plugin`, `disable_plugin`; reads and writes the scope's `plugins.json` and discovers the installed package's top-level modules
- `loader.py` — `register_plugin_tools` imports each enabled plugin's tool modules and registers their `TOOL_DEFS`; `register_plugin_hooks` does the same for hooks; `load_plugin_skills` returns the skill directories they ship
- `__init__.py` re-exports the public surface
