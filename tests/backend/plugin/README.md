# plugin/

## Purpose
Covers the plugin system, `bouzecode.backend.plugin` (manifest, store, loader,
types) and the launch-time installer `bouzecode.backend.multi_agent.plugin_resolver`.
Each test synthesises a real installable package on disk under `tmp_path`, puts it on
a temporary `sys.path` site directory, and exercises the real discovery and
registration code — no plugin is mocked.

## Usage
- `test_plugin_hooks.py` — a plugin exporting `HOOK_DEFS` gets its hook registered in the pipeline and referencable by name.
- `test_plugin_resolver.py` — `ensure_plugins` installs what a profile's `requires_plugins` asks for, returns the tool names, surfaces an install error, and handles a git source.
- `test_plugin_store.py` — `PluginManifest` parsing from an import root, a plugin tool module importing nothing from bouzecode, install registering and discovering its tool, and disable excluding it.
