# regression/removed/

## Purpose

Locks that a deleted feature stays deleted: its module is not importable, no command or tool
re-registers it, and the modules that once referenced it still import cleanly. The approach is
`importlib` probes guarded by `pytest.raises(ModuleNotFoundError)` plus inspection of the real
command dispatcher and tool registry.

## Usage

- `test_mcp_removed.py` — `bouzecode.backend.mcp` is gone, the dispatcher has no `mcp` command,
  `tools.registration` imports, and `commands.extensions.skills_mcp.cmd_skills` still works.
- `test_memory_removed.py` — `bouzecode.backend.memory` is gone, no memory tool appears in
  `get_all_tools`, and `tools.registration`, `commands` and `core.context` import without it.
- `test_brainstorm_removal.py` — the brainstorm module is unimportable, `core._embedded_data`
  exposes no brainstorm attribute, and `ui.repl_sentinels` and the package still import.
- `test_plugin_removed.py` — `/plugin` resolves through `commands.oss_shims.plugin_cmd` to the
  flat `plugin` package, `tools.registration` imports, and `core.paths.get_extra_dirs` works.
- `test_removal_cloudsave_voice_video.py` — the cloudsave, voice and video modules and their
  command modules are unimportable and absent from `COMMANDS` and `_CMD_META`, while
  `commands.core.basic.cmd_exit` and `ui.cli` are unaffected.
