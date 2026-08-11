# commands/oss_shims/

## Purpose
Thin wrappers that make the flat feature packages (`voice/`, `mcp/`, `plugin/`, `memory/`,
`video/`) dispatchable as slash commands. Each shim adapts the handler signature the
dispatcher calls, `(args, state, config)`, and every one degrades to a warning when its
package is absent rather than raising.

## Usage
- `__init__.py` — `OSS_COMMANDS` (the name → handler table the dispatcher reads), `OSS_COMMAND_META` (short help line and sub-commands per entry, consumed by `/help`), and `_echoing`, the decorator that prints a handler's string result because the dispatcher discards return values other than a sentinel tuple
- `voice_cmd.py` — `cmd_voice`: `/voice` records and transcribes, returning the `("__voice__", text)` sentinel the REPL sends on as a prompt; `/voice status` reports dependency availability. `_voice_status`, `_voice_record`
- `mcp_cmd.py` — `cmd_mcp`: `/mcp list|reload|add <name> <json>|remove <name>`
- `plugin_cmd.py` — `cmd_plugin`: `/plugin list|install|uninstall|enable|disable|load`
- `memory_cmd.py` — `cmd_memory`: `/memory list`, `/memory consolidate`, or any other argument treated as a search query
- `video_cmd.py` — `cmd_video`: delegates `/video` to the flat video pipeline command; without it, reports which pipeline dependencies are missing
- `video_wizard_cmd.py` — `cmd_video_wizard`: runs the step-by-step wizard, then invokes the pipeline with the topic it collected
