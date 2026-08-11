# tools/registry/

## Purpose

Covers `bouzecode.backend.core.tool_registry` — registering, listing, enabling and
executing tools — together with the slash-command layer in
`bouzecode.backend.commands` and the output capping in `tools.ops.truncation`.

Mostly direct unit calls against a registry cleaned by an autouse fixture, plus CLI
tests that drive the command functions over an isolated temp directory. One `_e2e` file
runs a conversation through the `bouzecode()` harness with `MockLLM`.

## Usage

- `test_tool_registry.py` — `ToolDef`, `register_tool`, `get_tool`, `get_all_tools`,
  `get_tool_schemas`, `execute_tool`, `clear_registry`, and result truncation.
- `test_tool_enable_disable.py` — `disable_tool`/`enable_tool` semantics (unknown names,
  idempotence, reset, listing), disabled tools dropped from the schemas the model sees
  yet still executable-by-handler, execution refused with an error, and the `/tools`
  command in `commands.core.basic.cmd_tools`.
- `test_tool_truncation.py` — `truncate_tool_output` caps by line count and by character
  count, writes the full text to a file, keeps a resolvable pointer to it, and its
  head-plus-tail window preserves the pytest verdict without duplicating lines.
- `test_invalid_param_listing.py` — an unknown tool parameter answers with an error that
  lists the valid parameter names.
- `test_commands_cli.py` — end-to-end `/init`, `/export`, `/copy` and `/status` against a
  temp directory.
- `test_commands_cleanup.py` — the `COMMANDS` dispatcher exposes the expected keys and
  not the retired ones, `cmd_info`, `cmd_doctor` and `handle_slash` import and answer
  help and unknown commands.
- `test_unavailable_tool_message_e2e.py` — a tool the agent cannot call gets a terminal
  refusal that names a substitute the agent really has; an unknown tool name gets the
  same treatment.
