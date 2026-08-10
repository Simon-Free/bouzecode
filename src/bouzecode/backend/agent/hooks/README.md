# Agent Hooks

An in-process hook pipeline for the agent loop. The core (`loop.py`) only ever
*fires* events; all orchestration lives in hook functions + the persisted ticket
state.

## Modules

- `pipeline.py` — two registries (mirror of the tool system):
  - **named-hook catalog** (`_NAMED`, name → `HookDef`), populated by bouzecode
    builtins and by plugins exporting `HOOK_DEFS`. A profile references a hook by
    name in its `hooks: [...]` list.
  - **event registry** (`_HOOKS`, event → [fn]) — the hooks wired for THIS
    process. `apply_profile_hooks` resolves the profile's names against the
    catalog and `register_hook`s them.
  - `fire(event, ctx)` invokes every hook wired to `event` (errors logged loudly,
    never abort the close). `reset()` / `reset_named()` clear per-process state.
- `context.py` — `HookContext`, the **stable API** handed to hooks: fields
  (`event, self_id, profile, run_kind, final_text, close_reason, config`) plus
  helper methods (`spawn_agent`, `continue_agent`, `ticket`, `http_post/http_get`)
  so a hook never imports `services/work/*` or `web/runner` directly.
- `completion.py` — the builtin `run_completion_chain` hook (event
  `on_completion`), wired by coder profiles. On graceful close it POSTs to
  `/api/tickets/<slug>/<id>/completed`; the server advances the workflow state
  machine.

## Events

- `on_completion` — fired at the end of `loop.run()` on a **graceful** close
  only (a FinalAnswer, or a text reply with no tool calls). NON-graceful exits
  (`assistant_none`, `partial_stream`, `cancelled`) do NOT fire it.

## Plugins

A plugin contributes hooks exactly like tools: its `plugin.json` lists `hooks`
modules, each exporting `HOOK_DEFS = [HookDef(name, event, fn), …]`. The plugin
loader imports them and registers into the named-hook catalog, so a profile can
reference a plugin hook by name.
